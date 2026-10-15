"""Render the matched CLI timings; requires matplotlib==3.11.2."""
import json
import math
import statistics
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
r = json.loads((ROOT / 'results.json').read_text())
assert r['full_suite_identical'] == 1100
assert len([x for x in r['rows'] if x['repeat'] >= 0]) == 864
for mode, datasets in r['summary'].items():
    for ds, arms in datasets.items():
        for arm, summary in arms.items():
            times = sorted(row['ms'] for row in r['rows'] if row['mode'] == mode
                           and row['dataset'] == ds and row['arm'] == arm and row['repeat'] >= 0)
            assert len(times) == summary['calls'] == 72
            assert statistics.median(times) == summary['p50_ms']
            assert times[math.ceil(.95 * len(times)) - 1] == summary['p95_ms']
blue, ink, muted, gray = '#2563eb', '#11162b', '#68738b', '#bac3d2'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'svg.fonttype': 'path',
                     'svg.hashsalt': 'sgrep-model2vec', 'text.color': ink})
fig = plt.figure(figsize=(16, 9), facecolor='white')
fig.text(.055, .90, 'model2vec-rs in sgrep', fontsize=30)
fig.text(.055, .846, 'Matched CLI latency · lower is better', fontsize=16, color=muted)
for left, ds, title in ((.17, 'repoqa', 'RepoQA'), (.64, 'cosqa', 'CoSQA')):
    ax = fig.add_axes([left, .28, .285, .43])
    maximum = max(r['summary'][m][ds][a]['p50_ms'] for m in r['summary'] for a in ('before', 'after'))
    for i, (mode, label) in enumerate((('warm', 'Cached query'), ('uncached', 'Uncached search'), ('pipe', 'Piped reranking'))):
        y = 2 - i
        values = [r['summary'][mode][ds][a]['p50_ms'] for a in ('before', 'after')]
        for arm, value, offset, color in zip(('before', 'after'), values, (.16, -.16), (gray, blue)):
            ax.barh(y + offset, value, height=.24, color=color)
            ax.text(value + maximum * .025, y + offset, f'{value:.1f} ms', va='center', fontsize=11, color=ink if arm == 'before' else blue)
        ratio = values[1] / values[0]
        ax.text(-maximum * .04, y, label, va='center', ha='right', fontsize=12)
        ax.text(maximum * 1.48, y, f'{ratio:.2f}×', va='center', ha='right', fontsize=14, color=blue)
    ax.set_xlim(0, maximum * 1.5)
    ax.set_ylim(-.5, 2.5)
    ax.set_yticks([])
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(title, loc='left', pad=24, fontsize=18)
    ax.text(1, 1.09, 'PR / main', transform=ax.transAxes, ha='right', fontsize=11, color=muted)
fig.text(.055, .203, '■  main', color=muted, fontsize=13)
fig.text(.16, .203, '■  PR with model2vec-rs 0.3.0', color=blue, fontsize=13)
fig.text(.055, .132, 'Identical top-20 results on all 1,100 queries. The existing embedder remains the default.', fontsize=14)
fig.text(.055, .084, 'Apple M5 Max · 24 fixed queries × 6 repeats × 3 modes × 2 builds · median elapsed time', fontsize=11, color=muted)
fig.text(.055, .052, 'Offline assets; separate indexes and panel scales. Pipe excludes ripgrep. Shared host; not a library throughput benchmark.', fontsize=10, color=muted)
fig.savefig(ROOT / 'benchmark.svg', metadata={'Date': None, 'Creator': 'Context.dev · sgrep'})
plt.close(fig)
# Use the repository's existing wordmark.
ET.register_namespace('', 'http://www.w3.org/2000/svg')
ns = '{http://www.w3.org/2000/svg}'
svg = ET.parse(ROOT / 'benchmark.svg')
logo = ET.parse(ROOT.parents[1] / 'assets/context-logo.svg').getroot()
group = ET.SubElement(svg.getroot(), ns + 'g', {'transform': 'translate(944 46) scale(0.18)'})
for child in logo:
    group.append(child)
svg.write(ROOT / 'benchmark.svg', encoding='unicode')
output = ROOT / 'benchmark.svg'
output.write_text('\n'.join(line.rstrip() for line in output.read_text().splitlines()) + '\n')
