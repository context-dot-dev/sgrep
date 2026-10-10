"""Render the measured benchmark charts. Run verify.py before regenerating."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "results.json").read_text())
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
    methods = [m for m in DATA["summary"][dataset] if m != "jevgrep" and not (dataset == "repoqa" and m == "ck-lex")]
    scores = DATA["summary"][dataset]
    ax.barh(range(len(methods)), [scores[m]["p50_ms"] for m in methods], color=[COLORS[m] for m in methods], height=.5)
    ax.set_yticks(range(len(methods)), [LABELS[m] for m in methods])
    ax.invert_yaxis()
    ax.set_xlim(0, max(scores[m]["p95_ms"] for m in methods) * 1.25)
    for y, method in enumerate(methods):
        median, p95 = scores[method]["p50_ms"], scores[method]["p95_ms"]
        ax.scatter([p95], [y], marker="|", s=120, color="#11162b")
        ax.annotate(f"{median:.0f} ms", (median, y), xytext=(5, -14), textcoords="offset points", fontsize=10)
    ax.set_title("RepoQA" if dataset == "repoqa" else "CoSQA", loc="left")
    ax.set_xlabel("Milliseconds · bar = median, tick = p95")
    ax.grid(axis="x", alpha=.14)
    ax.set_axisbelow(True)
finish(fig, "latency", "Warm local CLI latency",
       "M5 Max · Fresh CLI processes, cached assets/indexes · Shared-host load varied; observational timing.\nCK lexical used a separate repair pass. Jevgrep: 9.51 s median / 35.59 s p95, network-backed concurrent queries.")

languages = list(DATA["by_language"])
methods = ["sgrep-main", "ck-sem", "jevgrep", "ripgrep"]
values = [[100 * DATA["by_language"][lang][m]["full8000"] for m in methods] for lang in languages]
fig, ax = plt.subplots(figsize=(12, 6))
fig.subplots_adjust(left=.15, right=.94, bottom=.23, top=.75)
ax.imshow(values, cmap="Blues", vmin=0, vmax=100, aspect="auto")
ax.set_xticks(range(len(methods)), [LABELS[m] for m in methods])
ax.set_yticks(range(len(languages)), [{"cpp": "C++", "go": "Go", "java": "Java", "python": "Python", "rust": "Rust", "typescript": "TypeScript"}[l] for l in languages])
ax.tick_params(length=0, pad=10)
for y, row in enumerate(values):
    for x, value in enumerate(row):
        ax.text(x, y, f"{value:.0f}%", ha="center", va="center", color="white" if value > 65 else "#11162b", fontsize=14)
finish(fig, "languages", "Complete-function retrieval by language",
       "100 RepoQA questions per language · All target-function lines within 8,000 source tokens.\nsgrep 0fbe8e5 · Failed and partial searches retained · CK lexical rejects all 600 formatted queries.")
