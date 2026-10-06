"""Compare fresh CLI processes on a fixed query file; retain results and timings.

Failure contract: changed ranked source, skipped queries, warmed-model timing
reported as CLI latency, query-specific tuning, and hidden subprocess failures.
Input JSON: [{"id": "...", "query": "...", "root": "/path/to/code"}, ...].
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("before", type=Path)
parser.add_argument("after", type=Path)
parser.add_argument("queries", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
queries = json.loads(args.queries.read_text())
args.output.mkdir(parents=True, exist_ok=True)
rows = []
equal = []


def run(method, script, query, phase, repeat):
    start = time.perf_counter()
    command = [sys.executable, str(script)] if script.suffix == '.py' else [str(script)]
    result = subprocess.run(command + [query['query'], query['root'], '--json', '-n', '200'], capture_output=True, text=True, timeout=120)
    seconds = time.perf_counter() - start
    assert result.returncode in (0, 1), result.stderr
    blocks = json.loads(result.stdout)
    rows.append(dict(method=method, id=query['id'], phase=phase, repeat=repeat, seconds=seconds, results=len(blocks)))
    if phase == 'all':
        (args.output/f'{method}-{query["id"]}.json').write_text(json.dumps(blocks))
    return blocks


for i, q in enumerate(queries):
    arms = [('before', args.before), ('after', args.after)]
    if i % 2:
        arms.reverse()
    results = {m:run(m, script, q, 'all', 0) for m,script in arms}
    equal.append({'id':q['id'], 'identical':results['before']==results['after']})
    if (i+1) % 10 == 0:
        print(f'{i+1}/{len(queries)} queries compared', flush=True)
for q in (q for q in queries if q['id'].endswith('-00')):
    for repeat, method in enumerate(('before','after','after','before')):
        run(method, getattr(args,method), q, 'panel', repeat)
summary = {}
for phase in ('all','panel'):
    summary[phase] = {}
    for method in ('before','after'):
        times = sorted(r['seconds'] for r in rows if r['phase']==phase and r['method']==method)
        if times:
            summary[phase][method] = dict(n=len(times), median_ms=statistics.median(times)*1000, p95_ms=times[min(len(times)-1, int(.95*len(times)))]*1000)
receipt = dict(identical_rankings=all(r['identical'] for r in equal), comparisons=equal, summary=summary, rows=rows,
               conditions='Fresh CLI process per call, cached model files, filesystem caches not cleared. Python baselines use the runner interpreter; native binaries run directly. Same host, alternating methods. Panel uses ABBA ordering on query 00 per repository. No daemon or corpus index.')
(args.output/'summary.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({'identical_rankings':receipt['identical_rankings'], 'summary':summary},indent=2))
assert receipt['identical_rankings'], 'ranked results changed; inspect the saved JSON pairs'
