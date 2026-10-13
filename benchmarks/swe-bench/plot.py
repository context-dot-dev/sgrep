"""Rebuild the cost/quality chart from all 800 recorded attempts, without API calls."""
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import NullLocator

ROOT = Path(__file__).resolve().parent
analysis = json.loads((ROOT / "results/analysis.json").read_text())
with (ROOT / "results/attempts.csv").open() as stream:
    attempts = list(csv.DictReader(stream))
summary = {row["arm"]: row for row in analysis["summary"]}
assert analysis["complete"] and len(attempts) == 800
assert len({(r["task"], r["arm"], r["repeat"]) for r in attempts}) == 800
assert len({r["task"] for r in attempts}) == 50
for arm, result in summary.items():
    rows = [row for row in attempts if row["arm"] == arm]
    assert len(rows) == result["attempts"] == 100
    assert sum(int(row["resolved"]) for row in rows) == result["resolved"]
    mean = sum(float(row["api_cost_usd"]) for row in rows) / len(rows)
    assert abs(mean - result["mean_api_usd"]) < 1e-12

# Omit whole configurations with setup failures or search timeouts, never individual tasks.
shown = {arm: row for arm, row in summary.items()
         if not row["attempt_errors"] and not row["search_timeouts"]}
labels = {
    "sgrep-pipe": ("sgrep · pipe", (14, 10), "left"),
    "ripgrep": ("ripgrep", (-14, 0), "right"),
    "colgrep": ("ColGrep", (14, 6), "left"),
    "sgrep": ("sgrep · discovery", (14, -6), "left"),
    "jevgrep": ("Jevgrep", (14, 10), "left"),
}
assert shown.keys() == labels.keys()
plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path",
                     "svg.hashsalt": "sgrep-swe-bench"})
blue, ink, muted = "#2563eb", "#11162b", "#68738b"
fig = plt.figure(figsize=(16, 9), facecolor=blue)
fig.add_artist(Rectangle((.012, .021), .976, .958, transform=fig.transFigure,
                        facecolor="white", edgecolor="none", zorder=0))
fig.text(.08, .872, "SWE-bench Verified", fontsize=29, color=ink)
fig.text(.08, .815, "GPT-6 Luna · 50 tasks × 2 runs", fontsize=16, color=muted)
ax = fig.add_axes([.12, .17, .76, .56])
ax.set_xscale("log")
ax.set_xlim(.0032, .24)
ax.set_ylim(65, 72)
ax.set_xticks([.005, .01, .03, .1], ["$0.005", "$0.01", "$0.03", "$0.10"])
ax.xaxis.set_minor_locator(NullLocator())
ax.set_yticks([66, 68, 70, 72])
ax.set_xlabel("LLM API cost / attempt · log scale", fontsize=15, color=muted, labelpad=20)
ax.set_ylabel("Solved attempts (%)", fontsize=15, color=muted, labelpad=22)
ax.tick_params(length=0, labelsize=13, colors=muted, pad=12)
ax.set_axisbelow(True)
ax.grid(color="#e9edf5", linewidth=1)
for spine in ax.spines.values():
    spine.set_visible(False)
for arm, row in shown.items():
    name, offset, align = labels[arm]
    x, y = row["mean_api_usd"], 100 * row["solve_rate"]
    primary = arm == "sgrep-pipe"
    color = blue if primary else "#929baa"
    ax.scatter(x, y, s=135 if primary else 85, color=color, zorder=3)
    if row["incomplete_accounting"]:
        name += f"\n≥ ${x:.5f}"
    ax.annotate(name, (x, y), xytext=offset, textcoords="offset points",
                ha=align, va="center", fontsize=16,
                color=blue if primary else ink, weight="bold" if primary else "normal")
for extension in ("svg", "png"):
    metadata = {"Date": None, "Creator": "Context.dev"} if extension == "svg" else {}
    fig.savefig(ROOT / f"benchmark.{extension}", dpi=150, metadata=metadata)
svg = ROOT / "benchmark.svg"
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
plt.close(fig)
print(ROOT / "benchmark.svg")
