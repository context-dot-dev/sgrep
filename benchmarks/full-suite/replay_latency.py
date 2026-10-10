"""Replay frozen native commands on a hash-selected, balanced latency panel.

Failure contract (fixed before implementation): reject changed inputs/binaries;
keep failures and slow samples; separate preparation from timed queries; verify
ranked source against saved outputs; never treat repeats as independent queries.

Input is the original evidence bundle: corpus, queries, manifests, protocol and
records/{method}/{id}.json.gz under each dataset. Outputs include every native
stdout/stderr, a frozen selection, and a portable receipt. No model downloads.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

METHODS = ('sgrep-main', 'ck-sem', 'ripgrep')
REPEATS = 6


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def verify_sources(bundle):
    hashes = {}
    for repo in read(bundle / 'repoqa/manifest.json')['repositories']:
        root = bundle / 'repoqa/corpus' / Path(repo['root']).name
        files = {str(p.relative_to(root)): p.read_text() for p in root.rglob('*')
                 if p.is_file() and '.ck' not in p.parts and p.name != '.ckignore'}
        actual = digest(json.dumps(files, sort_keys=True).encode())
        assert actual == repo['sha256'], root
        hashes[root.name] = actual
    manifest = read(bundle / 'cosqa/manifest.json')
    root = bundle / 'cosqa/corpus'
    assert {p.name for p in root.iterdir() if p.is_file() and p.name != '.ckignore'} == set(manifest)
    for name, meta in manifest.items():
        assert digest((root / name).read_bytes()) == meta['sha256'], name
    hashes['cosqa'] = digest(json.dumps(manifest, sort_keys=True).encode())
    return hashes


def signature(stdout, method, dataset, root):
    """Compare ordered source, excluding scores and ripgrep's elapsed-time fields."""
    def path(value):
        p = Path(value)
        return str(p.relative_to(root) if p.is_absolute() else p).removeprefix('./')
    if method == 'sgrep-main':
        rows = [(path(x['path']), x['start'], x['end'], x['content']) for x in json.loads(stdout)]
    elif method == 'ripgrep' and dataset == 'cosqa':
        rows = [path(x) for x in stdout.splitlines()]
    else:
        rows = []
        for line in stdout.splitlines():
            x = json.loads(line)
            if method == 'ck-sem':
                rows.append((path(x['path']), x['span']['line_start'], x['span']['line_end'], x['snippet']))
            elif x['type'] == 'match':
                d = x['data']
                rows.append((path(d['path']['text']), d['line_number'], d['lines']['text']))
    return digest(json.dumps(rows, ensure_ascii=False).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = read(bundle / 'protocol.json')
    binaries = {m: protocol['binaries'][k] for m, k in zip(METHODS, ('sgrep-main', 'ck', 'rg'))}
    for meta in binaries.values():
        assert digest(Path(meta['path']).read_bytes()) == meta['sha256']
    source_hashes = verify_sources(bundle)
    groups = {}
    for q in read(bundle / 'repoqa/queries.json'):
        groups.setdefault(Path(q['root']).name, []).append(q)
    key = lambda q: digest(q['id'].encode())
    selected = {'repoqa': [min(qs, key=key) for _, qs in sorted(groups.items())],
                'cosqa': sorted(read(bundle / 'cosqa/queries.json'), key=key)[:60]}
    assert len(selected['repoqa']) == len(selected['cosqa']) == 60
    cases = []
    for ds, queries in selected.items():
        for q in queries:
            root = bundle / ds / 'corpus'
            if ds == 'repoqa':
                root /= Path(q['root']).name
            cases.append(dict(dataset=ds, id=q['id'], root=root, query=q['query']))
    frozen = {'selection': 'Minimum SHA256(id) per RepoQA repository; lowest 60 SHA256(id) on CoSQA.',
              'cases': [{k: str(v) if isinstance(v, Path) else v for k, v in c.items()} for c in cases],
              'repeats': REPEATS, 'methods': METHODS, 'source_hashes': source_hashes,
              'binaries': binaries, 'runner_sha256': digest(Path(__file__).read_bytes())}
    (output / 'frozen.json').write_text(json.dumps(frozen, indent=2))
    expected, commands = {}, {}
    for c in cases:
        ds, ident, root = c['dataset'], c['id'], c['root']
        for method in METHODS:
            native = json.loads(gzip.decompress((bundle / ds / 'records' / method / f'{ident}.json.gz').read_bytes()))
            old_root = Path(next(q['root'] for q in selected[ds] if q['id'] == ident)) if ds == 'repoqa' else bundle / ds / 'corpus'
            expected[ds, ident, method] = signature(native['stdout'], method, ds, old_root)
            commands[ds, ident, method] = [binaries[method]['path'], *native['argv'][1:]]
    env = dict(os.environ, HF_HUB_OFFLINE='1', SGREP_CACHE_DIR=str(output / 'indexes'))
    rows, prepared = [], set()
    for repeat in range(-1, REPEATS):
        # Shuffle within each dataset, then interleave them to reduce time-of-run bias.
        order = {ds: sorted([c for c in cases if c['dataset'] == ds],
                           key=lambda c: digest(f'{repeat}/{c["id"]}'.encode())) for ds in selected}
        ordered = [c for pair in zip(order['repoqa'], order['cosqa']) for c in pair]
        for i, c in enumerate(ordered):
            ds, ident, root = c['dataset'], c['id'], c['root']
            shift = (i + repeat + 1) % len(METHODS)
            for method in METHODS[shift:] + METHODS[:shift]:
                command = commands[ds, ident, method]
                load = os.getloadavg()[0]
                wall, start = time.time(), time.perf_counter()
                try:
                    p = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
                    stdout, stderr, code = p.stdout, p.stderr, p.returncode
                except subprocess.TimeoutExpired as e:
                    stdout, stderr, code = e.stdout or b'', e.stderr or b'', None
                elapsed, wall_elapsed = time.perf_counter() - start, time.time() - wall
                same = False
                try:
                    same = signature(stdout.decode(), method, ds, root) == expected[ds, ident, method]
                except (ValueError, KeyError, TypeError):
                    pass
                scope = (method, str(root))
                row = dict(dataset=ds, id=ident, method=method, repeat=repeat,
                           phase='prepare' if repeat < 0 else 'warm', first_scope=scope not in prepared,
                           ms=elapsed * 1000, clock_gap_ms=(wall_elapsed - elapsed) * 1000,
                           load1=load, returncode=code, same_ranked_source=same,
                           stdout_bytes=len(stdout), stdout_sha256=digest(stdout))
                prepared.add(scope)
                raw = output / 'native' / ds / method / f'{ident}.{repeat}.json.gz'
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(gzip.compress(json.dumps(dict(argv=command, stdout=stdout.decode(errors='replace'),
                    stderr=stderr.decode(errors='replace'), **row)).encode(), mtime=0))
                rows.append(row)
                with (output / 'samples.jsonl').open('a') as f:
                    f.write(json.dumps(row) + '\n')
            if (i + 1) % 20 == 0:
                print('repeat', repeat, 'cases', i + 1, flush=True)
    assert verify_sources(bundle) == source_hashes
    for meta in binaries.values():
        assert digest(Path(meta['path']).read_bytes()) == meta['sha256']
    warm = [r for r in rows if r['phase'] == 'warm']
    summary = {}
    for ds in selected:
        summary[ds] = {}
        for method in METHODS:
            sample = [r for r in warm if r['dataset'] == ds and r['method'] == method]
            times = sorted(r['ms'] for r in sample)
            query_medians = {q['id']: statistics.median(r['ms'] for r in sample if r['id'] == q['id']) for q in selected[ds]}
            summary[ds][method] = dict(calls=len(sample), queries=len(query_medians),
                p50_ms=statistics.median(times), p95_ms=times[int(.95 * len(times)) - 1],
                median_query_ms=statistics.median(query_medians.values()), query_medians=query_medians,
                errors=sum(r['returncode'] not in ((0, 1) if method != 'ck-sem' else (0,)) for r in sample))
    portable_cases = [dict(dataset=c['dataset'], id=c['id'], query_sha256=digest(c['query'].encode()),
                          scope=c['root'].name) for c in cases]
    receipt = dict(selection=frozen['selection'], cases=portable_cases, repeats=REPEATS,
        runner_sha256=frozen['runner_sha256'], binaries={m: v['sha256'] for m, v in binaries.items()},
        source_hashes=source_hashes, platform=platform.platform(), summary=summary, rows=rows,
        ranked_source_mismatches=sum(not r['same_ranked_source'] for r in rows),
        sleep_events=sum(abs(r['clock_gap_ms']) > 1000 for r in rows),
        conditions='Sequential fresh processes; one preparation pass, then six balanced repeats. Assets cached; OS caches not cleared. Shared host; no outlier removal. Repeats are not independent queries.')
    (output / 'receipt.json').write_text(json.dumps(receipt, separators=(',', ':')) + '\n')
    print(json.dumps({ds: {m: {k: v for k, v in s.items() if k != 'query_medians'} for m, s in mm.items()} for ds, mm in summary.items()}, indent=2))
    assert receipt['ranked_source_mismatches'] == receipt['sleep_events'] == 0, 'Inspect retained native outputs before publication'
    assert all(s['errors'] == 0 for mm in summary.values() for s in mm.values())


if __name__ == '__main__':
    main()
