"""Render CoSQA results: python benchmarks/plot_cosqa.py [--output PATH]."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--results", type=Path, default=Path(__file__).with_name("cosqa-results.json")
)
parser.add_argument("--output", type=Path, default=Path(__file__).with_name("cosqa"))
args = parser.parse_args()
data = json.loads(args.results.read_text())
methods = ["sgrep-main", "sgrep", "ck-sem", "ck-lex", "ripgrep"]
names = [
    "sgrep · current main",
    "sgrep · previous main",
    "CK semantic",
    "CK BM25",
    "ripgrep · literal OR",
]
colors = ["#2563eb", "#a4b7d3", "#59718f", "#59718f", "#59718f"]
plt.rcParams.update(
    {"font.family": "sans-serif", "font.size": 12, "svg.fonttype": "none"}
)
fig, axes = plt.subplots(1, 3, figsize=(14, 7), sharey=True)
fig.subplots_adjust(left=0.19, right=0.96, top=0.72, bottom=0.27, wspace=0.38)
fig.suptitle(
    "Code search beyond RepoQA", x=0.04, y=0.95, ha="left", fontsize=24, weight="bold"
)
fig.text(
    0.04,
    0.85,
    "CoSQA · all 500 test queries · 6,267 original Python snippets",
    fontsize=15,
    color="#526078",
)
for ax, metric, title in zip(
    axes,
    ("hit_at_1", "hit_at_10", "median_ms"),
    (
        "Correct first result (%)",
        "Correct result in top 10 (%)",
        "Median search time (ms)",
    ),
):
    values = [data["summary"][m][metric] for m in methods]
    if metric != "median_ms":
        values = [100 * v / data["summary"][m]["n"] for m, v in zip(methods, values)]
    ax.barh(range(len(methods)), values, height=0.52, color=colors)
    ax.set_title(title, loc="left", fontsize=12, pad=20)
    for i, value in enumerate(values):
        ax.annotate(
            f"{value:.1f}",
            (value, i),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=13,
        )
    ax.set_xlim(0, 100 if metric != "median_ms" else max(values) * 1.28)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#e3e8ef")
    ax.tick_params(axis="both", length=0, labelcolor="#526078")
    for spine in ax.spines.values():
        spine.set_visible(False)
axes[0].set_yticks(range(len(methods)), names)
axes[0].invert_yaxis()
index = data["index"]
fig.text(
    0.04,
    0.14,
    f"CK preindex: {index['seconds']:.1f}s; combined indexes: {index['persistent_bytes_after_queries'] / 1e6:.1f} MB. sgrep and ripgrep: no corpus index.",
    fontsize=11,
    color="#526078",
)
fig.text(
    0.04,
    0.09,
    "Fresh CLI processes; cached models. Current sgrep timed in a separate phase; filesystem caches not cleared.",
    fontsize=10,
    color="#526078",
)
fig.text(
    0.04,
    0.045,
    "Python snippets, original docstrings, one labeled answer per query. No tuning · October 9, 2026 · Apple M5 Max.",
    fontsize=10,
    color="#526078",
)
for extension in ("svg", "png"):
    fig.savefig(
        args.output.with_suffix("." + extension),
        dpi=160,
        facecolor="white",
        metadata={"Date": None} if extension == "svg" else {},
    )
svg = args.output.with_suffix(".svg")
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
