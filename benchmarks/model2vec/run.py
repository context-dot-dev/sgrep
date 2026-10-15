"""Paired CLI benchmark against the frozen RepoQA/CoSQA evidence bundle.

Failure contract: altered source/binaries, truncated text, changed ranked source,
unreported failures, warm/cold conflation, cherry-picked queries or outliers.
The receipt retains all timings; native stdout/stderr are saved as gzip JSON.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import runpy
import statistics
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bundle = args.bundle.resolve()
    verify = runpy.run_path(str(Path(__file__).parents[1] / 'full-suite/replay_latency.py'))['verify_sources']
    hashes = verify(bundle)
    binaries = {arm: getattr(args, arm).resolve() for arm in ('before', 'after')}
    binary_hashes = {arm: digest(p.read_bytes()) for arm, p in binaries.items()}
    cases = []
    for ds in ('repoqa', 'cosqa'):
        for q in read(bundle / ds / 'queries.json'):
            root = bundle / ds / 'corpus'
            if ds == 'repoqa':
                root /= Path(q['root']).name
            cases.append(dict(dataset=ds, id=q['id'], query=q['query'], root=str(root),
                              language=q.get('language', 'python')))
    assert len(cases) == 1100
    groups = {}
    for case in cases:
        if case['dataset'] == 'repoqa':
            groups.setdefault(case['language'], []).append(case)
    panel = [c for language in sorted(groups)
             for c in sorted(groups[language], key=lambda c: digest(c['id'].encode()))[:2]]
    panel += sorted([c for c in cases if c['dataset'] == 'cosqa'],
                    key=lambda c: digest(c['id'].encode()))[:12]
    assert len(panel) == 24
    rows, pipes, expected = [], {}, {}
    for c in panel:
        root = Path(c['root'])
        paths = subprocess.check_output(['rg', '--files', '-0'], cwd=root).split(b'\0')
        paths = sorted(p for p in paths if p)[:20]
        p = subprocess.run(['rg', '--json', '-C', '3', '-m', '2', '-e',
                            'return|throw|raise|error', '--', *map(os.fsdecode, paths)],
                           cwd=root, capture_output=True)
        assert p.returncode == 0, (c['id'], p.stderr)
        pipes[c['id']] = p.stdout
    (out / 'inputs.json').write_text(json.dumps(dict(cases=cases, panel=[c['id'] for c in panel],
        pipe_sha256={k: digest(v) for k, v in pipes.items()}, source_hashes=hashes), indent=2))

    def run(c, mode, repeat, arm):
        command = [str(binaries[arm]), c['query'], c['root'], '--json', '-n', '20']
        if mode == 'uncached':
            command.append('--no-cache')
        elif mode == 'pipe':
            command.append('--stdin')
        env = os.environ | {'HF_HUB_OFFLINE': '1', 'SGREP_CACHE_DIR': str(out / 'indexes' / arm),
                            'SGREP_CACHE_MAX_BYTES': str(1024 * 1024 * 1024)}
        start, wall = time.perf_counter(), time.time()
        p = subprocess.run(command, input=pipes[c['id']] if mode == 'pipe' else None,
                           cwd=c['root'], capture_output=True, env=env, timeout=180)
        elapsed, gap = time.perf_counter() - start, time.time() - wall
        row = dict(id=c['id'], dataset=c['dataset'], mode=mode, repeat=repeat, arm=arm,
                   ms=elapsed * 1000, clock_gap_ms=(gap - elapsed) * 1000,
                   returncode=p.returncode, stdout_sha256=digest(p.stdout))
        raw = out / 'native' / f'{c["id"]}.{mode}.{repeat}.{arm}.json.gz'
        raw.parent.mkdir(exist_ok=True)
        raw.write_bytes(gzip.compress(json.dumps(dict(command=command, stdout=p.stdout.decode(),
                         stderr=p.stderr.decode(), **row)).encode(), mtime=0))
        rows.append(row)
        with (out / 'samples.jsonl').open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        assert p.returncode == 0, (row, p.stderr)
        return p.stdout

    # Full-suite parity pass also builds each arm's independent indexes.
    for i, c in enumerate(cases):
        outputs = {arm: run(c, 'parity', -1, arm) for arm in ('before', 'after')}
        assert outputs['before'] == outputs['after'], c['id']
        expected[c['id']] = digest(outputs['before'])
        if (i + 1) % 100 == 0:
            print(f'Full-suite parity: {i + 1}/1100', flush=True)
    # One untimed preparation per mode, followed by six balanced paired repeats.
    for repeat in range(-1, 6):
        for i, c in enumerate(sorted(panel, key=lambda c: digest(f'{repeat}/{c["id"]}'.encode()))):
            for mode in ('warm', 'uncached', 'pipe'):
                arms = ('before', 'after') if (i + repeat) % 2 == 0 else ('after', 'before')
                outputs = {arm: run(c, mode, repeat, arm) for arm in arms}
                assert outputs['before'] == outputs['after'], (c['id'], mode, repeat)
                if mode != 'pipe':
                    assert digest(outputs['before']) == expected[c['id']], (c['id'], mode)
        print(f'Timing repeat {repeat} complete', flush=True)
    assert verify(bundle) == hashes
    assert {arm: digest(p.read_bytes()) for arm, p in binaries.items()} == binary_hashes
    assert all(abs(r['clock_gap_ms']) < 1000 for r in rows), 'Host sleep detected; keep this run but do not publish its timings'
    summary = {}
    for mode in ('warm', 'uncached', 'pipe'):
        summary[mode] = {}
        for ds in ('repoqa', 'cosqa'):
            summary[mode][ds] = {}
            for arm in binaries:
                sample = [r for r in rows if r['mode'] == mode and r['dataset'] == ds
                          and r['arm'] == arm and r['repeat'] >= 0]
                times = sorted(r['ms'] for r in sample)
                summary[mode][ds][arm] = dict(calls=len(times), p50_ms=statistics.median(times),
                    p95_ms=times[math.ceil(.95 * len(times)) - 1])
    receipt = dict(summary=summary, full_suite_identical=1100, panel_queries=24, repeats=6,
        binary_sha256=binary_hashes, source_hashes=hashes, runner_sha256=digest(Path(__file__).read_bytes()),
        platform=platform.platform(), cpu=subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip() if platform.system() == 'Darwin' else platform.processor(),
        conditions='Sequential fresh CLI processes; offline model/parser assets; separate prepared indexes; warm OS file cache; no outlier removal. Pipe timings exclude the fixed ripgrep producer. Shared host; repeats are not independent queries.',
        selection='Two lowest SHA256(query id) per RepoQA language, twelve lowest on CoSQA; six balanced repeats per case/mode/arm.',
        panel=[dict(id=c['id'], dataset=c['dataset'], query_sha256=digest(c['query'].encode()), scope=Path(c['root']).name) for c in panel],
        rows=rows)
    (out / 'results.json').write_text(json.dumps(receipt, separators=(',', ':')) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
