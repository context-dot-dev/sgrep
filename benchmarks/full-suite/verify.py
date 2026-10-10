"""Recompute published aggregates from every scored row; no model or network calls."""
import collections
import csv
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
results = json.loads((ROOT / "results.json").read_text())
rows = results["rows"]
assert len(rows) == 5000
assert len({(r["dataset"], r["method"], r["id"]) for r in rows}) == len(rows)

def aggregate(group):
    n = len(group)
    times = sorted(r["seconds"] * 1000 for r in group)
    out = dict(n=n, errors=sum(r["status"] == "error" for r in group),
               incomplete=sum(r["status"] not in ("complete", "error") for r in group),
               statuses=dict(collections.Counter(r["status"] for r in group)),
               p50_ms=statistics.median(times), max_ms=max(times))
    for p in (95, 99):
        out[f"p{p}_ms"] = times[math.ceil(p / 100 * n) - 1]
    for k in (1, 5, 10, 100):
        out[f"hit{k}"] = sum(r["rank"] is not None and r["rank"] <= k for r in group) / n
    out["mrr10"] = sum(1 / r["rank"] for r in group if r["rank"] is not None and r["rank"] <= 10) / n
    if group[0]["dataset"] == "repoqa":
        for metric, budget in (("half", 2000), ("half", 8000), ("full", 8000)):
            out[f"{metric}{budget}"] = sum(r["hits"][str(budget)][metric] for r in group) / n
    return out

def compare(actual, expected):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        if isinstance(value, dict):
            assert actual[key] == value, key
        else:
            assert math.isclose(actual[key], value, rel_tol=1e-12, abs_tol=1e-12), key

for dataset, methods in results["summary"].items():
    ids = None
    for method, expected in methods.items():
        group = [r for r in rows if r["dataset"] == dataset and r["method"] == method]
        assert len(group) == (600 if dataset == "repoqa" else 500)
        current_ids = {r["id"] for r in group}
        if ids is not None:
            assert current_ids == ids
        ids = current_ids
        compare(aggregate(group), expected)
for language, methods in results["by_language"].items():
    for method, expected in methods.items():
        group = [r for r in rows if r.get("language") == language and r["method"] == method]
        assert len(group) == 100
        compare(aggregate(group), expected)
with (ROOT / "summary.csv").open() as f:
    for row in csv.DictReader(f):
        expected = results["summary"][row["dataset"]][row["method"]]
        for key, value in row.items():
            if key in expected and value:
                assert math.isclose(float(value), expected[key], rel_tol=1e-12, abs_tol=1e-12)
print(json.dumps({"scored_rows": len(rows), "datasets": 2, "languages": 6,
                  "aggregate_and_csv_disagreements": 0,
                  "scope": "Aggregate replay from scored rows; original source and native-output validation was performed before publication."}, indent=2))
