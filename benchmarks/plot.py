"""Render the published code-search results with Python and matplotlib."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import NullLocator

ROOT = Path(__file__).resolve().parent
scores = json.loads((ROOT / "results.json").read_text())["summary"]
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"], "svg.fonttype": "none", "svg.hashsalt": "sgrep"})
blue, ink, muted, gray, grid = "#2563eb", "#11162b", "#68738b", "#a6acb8", "#e9edf5"
fig = plt.figure(figsize=(16, 10), facecolor=blue)
fig.add_artist(Rectangle((.012, .02), .976, .96, transform=fig.transFigure, facecolor="white", edgecolor="#dce8ff", linewidth=1, zorder=0))
frame = fig.add_axes([0, 0, 1, 1], zorder=-1)
frame.set(xlim=(0, 1600), ylim=(0, 1000)); frame.axis("off")
for y in (10, 990):
    frame.scatter(range(10, 1600, 24), [y] * len(range(10, 1600, 24)), s=4, facecolors="none", edgecolors="#d7e8ff", linewidths=.7)
for x in (10, 1590):
    frame.scatter([x] * len(range(10, 1000, 24)), range(10, 1000, 24), s=4, facecolors="none", edgecolors="#d7e8ff", linewidths=.7)
fig.text(.055, .865, "Code search accuracy and latency", fontsize=30, color=ink, weight="normal")
fig.text(.055, .807, "sgrep alongside CK, Jevgrep, and ripgrep on a RepoQA sample", fontsize=16, color=muted)
quality = fig.add_axes([.285, .23, .28, .43])
latency = fig.add_axes([.69, .23, .245, .43])
for ax in (quality, latency):
    ax.set_ylim(-.5, 3.5); ax.set_yticks([])
    ax.set_axisbelow(True); ax.grid(axis="x", color=grid, linewidth=1)
    ax.tick_params(axis="x", colors=muted, labelsize=12, length=0, pad=14)
    for spine in ax.spines.values(): spine.set_visible(False)
quality.set_xlim(0, 100); quality.set_xticks([0, 25, 50, 75, 100])
latency.set_xscale("log"); latency.set_xlim(10, 35000)
latency.set_xticks([10, 100, 1000, 10000], ["10", "100", "1,000", "10,000"])
latency.xaxis.set_minor_locator(NullLocator())
fig.text(.285, .728, "Function retrieval (%)", fontsize=17, color=ink)
fig.text(.285, .692, "Higher is better ↑", fontsize=13, color=muted)
fig.text(.69, .728, "Median latency (ms)", fontsize=17, color=ink)
fig.text(.69, .692, "Lower is better ↓ · logarithmic scale", fontsize=12, color=muted)
for i, (key, name, detail) in enumerate([
    ("sgrep", "sgrep", "v0.2.0 · code embeddings"),
    ("ck", "CK", "v0.7.11 · bge-small"),
    ("jevgrep", "Jevgrep", "dzhng · TypeSafe jev-1.13.0"),
    ("ripgrep", "ripgrep", "Literal query words"),
]):
    y = 3 - i; color = blue if key == "sgrep" else gray
    value = scores[key]["hit8k"] * 100; ms = scores[key]["median_ms"]
    quality.barh(y, value, height=.36, color=color)
    quality.text(value+3, y, f"{value:.1f}%", va="center", color=blue if key=="sgrep" else muted, fontsize=17, weight="normal")
    latency.scatter([ms], [y], s=100, color=color, zorder=3)
    latency.text(ms*1.28, y, f"{ms:,.0f}", va="center", fontsize=17, color=blue if key=="sgrep" else muted, weight="normal")
    fy = .23 + .43*(y+.5)/4
    fig.text(.063, fy+.006, name, fontsize=20, color=blue if key=="sgrep" else ink, weight="normal")
    fig.text(.063, fy-.025, detail, fontsize=11, color=muted)
fig.text(.055, .122, "Retrieval means ≥50% of the target function within 8,000 source tokens; file-location accuracy is reported separately.", fontsize=10.5, color=muted)
fig.text(.055, .092, "Quality: 60 queries across 12 repositories and 6 languages. Latency: a separate 12-query replay on an M5 Max.", fontsize=10.5, color=muted)
fig.text(.055, .062, "October 6, 2026 · Cached models and indexes · 12 MB of source snapshots · See methodology for setup costs and limits.", fontsize=10.5, color=muted)
output = ROOT / "benchmark.svg"
fig.savefig(output, metadata={"Date": None, "Creator": "Context.dev · sgrep"})
plt.close(fig)
# Reuse Context's vector wordmark without rasterizing it.
ET.register_namespace("", "http://www.w3.org/2000/svg")
ns = "{http://www.w3.org/2000/svg}"
svg = ET.parse(output)
svg.getroot().set("width", "1600")
svg.getroot().set("height", "1000")
logo = ET.parse(ROOT / "context.svg").getroot()
logo.set("x", "920"); logo.set("y", "44"); logo.set("width", "176"); logo.set("height", "31")
svg.getroot().append(logo)
title = ET.Element(ns+"title"); title.text = "sgrep code-search benchmark: 76.7% function retrieval at 71 ms median latency."
svg.getroot().insert(0, title)
svg.write(output, encoding="unicode", xml_declaration=True)
