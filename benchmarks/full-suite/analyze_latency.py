"""Analyze paired per-query medians; repeats are not independent observations."""
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def analyze(receipt):
    out = {}
    for dataset, methods in receipt['summary'].items():
        baseline = methods['sgrep-main']['query_medians']
        out[dataset] = {}
        for method, values in methods.items():
            if method == 'sgrep-main':
                continue
            assert baseline.keys() == values['query_medians'].keys()
            ratios = [values['query_medians'][q] / baseline[q] for q in sorted(baseline)]
            rng = random.Random(20261010)
            samples = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
            out[dataset][method] = dict(query_pairs=len(ratios), median_ratio=statistics.median(ratios),
                bootstrap_95=[samples[249], samples[9749]],
                meaning='Comparator / sgrep time; >1 means the comparator took longer. Not quality-adjusted.')
    return dict(repeats_collapsed_first=True, bootstrap_draws=10000, seed=20261010,
                limitation='Query-level panel uncertainty on one shared host; not a general speedup estimate.', paired=out)


if __name__ == '__main__':
    receipt = json.loads((ROOT / 'latency-replay.json').read_text())
    assert receipt['ranked_source_mismatches'] == receipt['sleep_events'] == 0
    (ROOT / 'latency-analysis.json').write_text(json.dumps(analyze(receipt), indent=2) + '\n')
