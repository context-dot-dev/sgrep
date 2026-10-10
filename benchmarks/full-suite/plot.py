"""Render the measured benchmark charts. Run verify.py before regenerating."""
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "results.json").read_text())
TIMING = json.loads((ROOT / "latency-replay.json").read_text())
LABELS = {"sgrep-main": "sgrep", "ck-sem": "CK semantic", "ck-lex": "CK lexical",
          "ripgrep": "ripgrep · literal OR", "jevgrep": "Jevgrep"}
COLORS = {"sgrep-main": "#2563eb", "ck-sem": "#344054", "ck-lex": "#8793a6",
          "ripgrep": "#bcc4d0", "jevgrep": "#697586"}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"], "font.size": 11,
                     "svg.fonttype": "none", "svg.hashsalt": "sgrep-full-20261009",
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.spines.left": False, "axes.spines.bottom": False,
                     "text.color": "#11162b", "axes.labelcolor": "#68738b",
                     "xtick.color": "#68738b", "ytick.color": "#11162b"})

def finish(fig, name, title, footnote):
    fig.patch.set_facecolor("#2563eb")
    fig.add_artist(Rectangle((.008, .018), .984, .964, transform=fig.transFigure,
                            facecolor="white", edgecolor="none", zorder=-1))
    fig.suptitle(title, x=.055, ha="left", y=.935, fontsize=21, weight="bold")
    fig.text(.055, .055, footnote, fontsize=9, color="#68738b")
    fig.savefig(ROOT / f"{name}.svg", metadata={"Date": None, "Creator": "Context.dev · sgrep"})
    output = ROOT / f"{name}.svg"
    output.write_text("\n".join(line.rstrip() for line in output.read_text().splitlines()) + "\n")
    plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.subplots_adjust(left=.16, right=.94, bottom=.23, top=.73, wspace=.85)
for ax, dataset, metric in zip(axes, ["repoqa", "cosqa"], ["full8000", "hit10"]):
    methods = ["sgrep-main", "ck-sem", "jevgrep", "ripgrep"] if dataset == "repoqa" else ["sgrep-main", "ck-sem", "ck-lex", "ripgrep"]
    values = [100 * DATA["summary"][dataset][m][metric] for m in methods]
    bars = ax.barh(range(len(methods)), values, color=[COLORS[m] for m in methods], height=.55)
    ax.set_yticks(range(len(methods)), [LABELS[m] for m in methods])
    ax.invert_yaxis()
    ax.set_xlim(0, 110)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
    ax.bar_label(bars, labels=[f"{v:.1f}%" for v in values], padding=5, fontsize=11)
    ax.set_title("RepoQA\nComplete function within 8k tokens" if dataset == "repoqa" else "CoSQA\nLabeled snippet in top 10", loc="left", pad=18)
    ax.grid(axis="x", alpha=.14)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
finish(fig, "overview", "sgrep benchmarks",
       "600 RepoQA / 500 CoSQA questions · sgrep 0fbe8e5 · October 2026\nCK lexical rejected RepoQA queries. Jevgrep ran on RepoQA only. Higher is better.")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.subplots_adjust(left=.09, right=.95, bottom=.25, top=.73, wspace=.3)
for ax, dataset in zip(axes, ["repoqa", "cosqa"]):
    cutoffs = [1, 5, 10] if dataset == "repoqa" else [1, 5, 10, 100]
    for method, scores in DATA["summary"][dataset].items():
        if dataset == "repoqa" and method == "ck-lex":
            continue
        ax.plot(cutoffs, [100 * scores[f"hit{k}"] for k in cutoffs],
                color=COLORS[method], marker="o", label=LABELS[method], linewidth=2.5,
                linestyle="--" if method in ("ck-lex", "jevgrep") else "-")
    ax.set_xscale("log")
    ax.set_xticks(cutoffs, [str(k) for k in cutoffs])
    ax.set_ylim(0, 100)
    ax.set_xlabel("Rank cutoff")
    ax.set_ylabel("Questions with the labeled result (%)")
    ax.set_title("RepoQA · target file" if dataset == "repoqa" else "CoSQA · target snippet", loc="left")
    ax.grid(alpha=.14)
handles = {}
for ax in axes:
    for handle, label in zip(*ax.get_legend_handles_labels()):
        handles[label] = handle
fig.legend(handles.values(), handles.keys(), loc="lower center", bbox_to_anchor=(.5, .105), ncol=5, frameon=False, fontsize=10)
finish(fig, "ranking", "How far down is the right result?",
       "600 RepoQA / 500 CoSQA queries · sgrep 0fbe8e5 · Final-output ranks, not isolated pre-reranker recall.\nCK lexical rejects RepoQA descriptions. Jevgrep was evaluated on RepoQA only.")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.subplots_adjust(left=.17, right=.95, bottom=.26, top=.73, wspace=.8)
for ax, dataset in zip(axes, ["repoqa", "cosqa"]):
    scores = TIMING["summary"][dataset]
    methods = list(scores)
    ax.barh(range(len(methods)), [scores[m]["p50_ms"] for m in methods], color=[COLORS[m] for m in methods], height=.5)
    ax.set_yticks(range(len(methods)), [LABELS[m] for m in methods])
    ax.invert_yaxis()
    ax.set_xlim(0, max(scores[m]["p95_ms"] for m in methods) * 1.7)
    for y, method in enumerate(methods):
        median, p95 = scores[method]["p50_ms"], scores[method]["p95_ms"]
        ax.scatter([p95], [y], marker="|", s=120, color="#11162b")
        ax.annotate(f"{median:.0f} / {p95:.0f} ms", (p95, y), xytext=(8, 0),
                    textcoords="offset points", fontsize=10, va="center")
    ax.set_title("RepoQA" if dataset == "repoqa" else "CoSQA", loc="left")
    ax.set_xlabel("Milliseconds · bar = median, tick = p95")
    ax.grid(axis="x", alpha=.14)
    ax.set_axisbelow(True)
finish(fig, "latency", "Repeated CLI latency · median / p95",
       "60 queries per dataset × 6 repeats = 360 calls per tool per dataset · sgrep 0fbe8e5 · October 10, 2026\nM5 Max · Fresh processes, warm models/indexes · Sequential, rotated tool order · Shared host; no outlier removal.")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.subplots_adjust(left=.10, right=.95, bottom=.24, top=.73, wspace=.3)
for ax, dataset in zip(axes, ["repoqa", "cosqa"]):
    ids = {c["id"] for c in TIMING["cases"] if c["dataset"] == dataset}
    for method, scores in TIMING["summary"][dataset].items():
        rows = [r for r in DATA["rows"] if r["dataset"] == dataset and r["method"] == method and r["id"] in ids]
        assert len(rows) == len(ids) == 60
        hits = [r["hits"]["8000"]["full"] if dataset == "repoqa" else r["rank"] is not None and r["rank"] <= 10 for r in rows]
        accuracy = 100 * sum(hits) / len(hits)
        ax.scatter(scores["median_query_ms"], accuracy, color=COLORS[method], s=75)
        ax.annotate(LABELS[method], (scores["median_query_ms"], accuracy), xytext=(7, 8), textcoords="offset points", fontsize=10)
    ax.set_xscale("log")
    ax.set_xlim(5, 2000)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Median query time (ms, log scale) · lower is better")
    ax.set_ylabel("Queries with the target (%)")
    ax.set_title("RepoQA · complete function within 8k tokens" if dataset == "repoqa" else "CoSQA · labeled snippet in top 10", loc="left", fontsize=11)
    ax.grid(alpha=.14)
finish(fig, "tradeoff", "Quality and time on the same queries",
       "60 fixed queries per dataset · Each query time is its median over 6 runs · Output source matches original scoring.\nThis is retrieval quality, not agent task success. Fixed-word ripgrep is not an agent choosing regexes.")

fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
fig.subplots_adjust(left=.19, right=.95, bottom=.28, top=.70, wspace=.9)
for ax, dataset in zip(axes, ["repoqa", "cosqa"]):
    initial = [r for r in TIMING["rows"] if r["method"] == "sgrep-main" and r["dataset"] == dataset and r["first_scope"]]
    warm = TIMING["summary"][dataset]["sgrep-main"]["query_medians"]
    values = [statistics.median(r["ms"] for r in initial), statistics.median(warm[r["id"]] for r in initial)]
    bars = ax.barh([0, 1], values, height=.5, color=["#344054", "#2563eb"])
    ax.set_yticks([0, 1], ["Empty index", "Warm index"])
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.45)
    ax.bar_label(bars, labels=[f"{v:.0f} ms" for v in values], padding=6, fontsize=11)
    ax.set_title(f"{'RepoQA' if dataset == 'repoqa' else 'CoSQA'} · {len(initial)} scope" + ("s" if len(initial) != 1 else ""), loc="left")
    ax.set_xlabel("Median time (ms)")
    ax.grid(axis="x", alpha=.14)
    ax.set_axisbelow(True)
finish(fig, "setup", "sgrep: first search vs warm repeat",
       "Same query per scope · Model/parser assets cached · OS caches not cleared · sgrep 0fbe8e5\nCoSQA setup is one observation. CK fresh index construction and model downloads are not measured here.")

languages = list(DATA["by_language"])
methods = ["sgrep-main", "ck-sem", "jevgrep", "ripgrep"]
fig, ax = plt.subplots(figsize=(12, 9))
fig.subplots_adjust(left=.15, right=.91, bottom=.21, top=.82)
for offset, method in enumerate(methods):
    positions = [i + (offset - 1.5) * .18 for i in range(len(languages))]
    values = [100 * DATA["by_language"][lang][method]["full8000"] for lang in languages]
    bars = ax.barh(positions, values, height=.16, color=COLORS[method], label=LABELS[method])
    ax.bar_label(bars, labels=[f"{v:.0f}%" for v in values], padding=4, fontsize=9)
ax.set_yticks(range(len(languages)), [{"cpp": "C++", "go": "Go", "java": "Java", "python": "Python", "rust": "Rust", "typescript": "TypeScript"}[l] for l in languages])
ax.invert_yaxis()
ax.set_xlim(0, 110)
ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
ax.tick_params(length=0, pad=10)
ax.grid(axis="x", alpha=.14)
ax.set_axisbelow(True)
ax.legend(loc="upper center", bbox_to_anchor=(.5, -.09), ncol=4, frameon=False, fontsize=10)
finish(fig, "languages", "Complete-function retrieval by language",
       "100 RepoQA questions per language · All target-function lines within 8,000 source tokens.\nsgrep 0fbe8e5 · CK lexical rejected all RepoQA queries. Higher is better.")
