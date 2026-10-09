"""Paired end-to-end CLI timing and exact output parity; retain every sample.

Cases are JSON objects with name, cwd, args and optional input_command (a producer
such as rg --json). The first pair per case is reported separately from warm runs.
Example: python tests/latency.py BEFORE AFTER cases.json results.json --repeats 10
"""
import argparse, hashlib, json, math, os, platform, statistics, subprocess, time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('before', type=Path)
parser.add_argument('after', type=Path)
parser.add_argument('cases', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--repeats', type=int, default=10)
args = parser.parse_args()
if args.repeats < 2:
    parser.error('at least two repeats are required')
binaries = {name: getattr(args, name).resolve() for name in ('before', 'after')}
cases = json.loads(args.cases.read_text())
rows = []
for case in cases:
    for repeat in range(args.repeats):
        row = {'case': case['name'], 'repeat': repeat, 'arms': {}}
        outputs = {}
        for name in (('before', 'after') if repeat % 2 == 0 else ('after', 'before')):
            start = time.perf_counter()
            producer = None
            if case.get('input_command'):
                producer = subprocess.Popen(case['input_command'], cwd=case['cwd'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = subprocess.run([str(binaries[name]), *case['args']], cwd=case['cwd'], stdin=producer.stdout if producer else subprocess.DEVNULL, capture_output=True, timeout=180)
            if producer:
                producer.stdout.close()
                producer.stdout = None
                _, error = producer.communicate(timeout=180)
                assert producer.returncode in (0, 1), error
            elapsed = (time.perf_counter() - start) * 1000
            row['arms'][name] = {'ms': elapsed, 'exit_code': result.returncode, 'stderr': result.stderr.decode(), 'stdout_sha256': hashlib.sha256(result.stdout).hexdigest()}
            outputs[name] = result.stdout
        row['exact_parity'] = outputs['before'] == outputs['after'] and row['arms']['before']['exit_code'] == row['arms']['after']['exit_code']
        rows.append(row)
        args.output.write_text(json.dumps({'cases': cases, 'rows': rows}, indent=2))
        assert all(arm['exit_code'] in (0, 1) for arm in row['arms'].values()), row
        assert row['exact_parity'], row
        print(case['name'], repeat, {n: round(a['ms'], 1) for n, a in row['arms'].items()}, flush=True)
summary = {}
for case in cases:
    summary[case['name']] = {}
    for name in binaries:
        selected = [r['arms'][name]['ms'] for r in rows if r['case'] == case['name']]
        warm = sorted(selected[1:])
        summary[case['name']][name] = {'first_ms': selected[0], 'warm_median_ms': statistics.median(warm), 'warm_p95_ms': warm[math.ceil(len(warm) * .95) - 1], 'warm_max_ms': max(warm)}
receipt = {'platform': platform.platform(), 'binaries': {n: {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for n, p in binaries.items()}, 'cache': os.environ.get('SGREP_CACHE_DIR'), 'cases': cases, 'summary': summary, 'rows': rows}
args.output.write_text(json.dumps(receipt, indent=2))
print(json.dumps(summary, indent=2))
