# Code-search benchmarks

## CoSQA: full retrieval test

[CoSQA](https://github.com/Jun-jie-Huang/CoCLR) provides real web-search queries paired with Python code. This October 9, 2026 comparison uses **all 500 test queries and all 6,267 original snippets** at upstream commit `14ebcacf9e9bc3e7109102632bc63047876f27d2`. The 500 queries refer to 472 distinct labeled snippets. No model or query tuning was performed.

![CoSQA accuracy and latency](cosqa.svg)

| Tool | Hit@1 | Hit@5 | Hit@10 | MRR@10 | Median | p95 | Errors / 500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sgrep (current main) | 27.2% | 52.6% | 61.6% | 0.376 | 108.3 ms | 137.2 ms | 0 |
| sgrep (previous main) | 25.6% | 51.4% | 60.4% | 0.364 | 122.4 ms | 166.9 ms | 0 |
| CK semantic | 38.0% | 69.6% | 79.6% | 0.515 | 392.8 ms | 539.9 ms | 0 |
| CK BM25 | 22.0% | 41.8% | 52.8% | 0.309 | 100.2 ms | 139.4 ms | 6 |
| ripgrep (literal OR) | 0.0% | 0.6% | 1.0% | 0.002 | 90.9 ms | 129.0 ms | 0 |

Current sgrep improved Hit@10 from 60.4% to 61.6%, while CK semantic reached 79.6%. CK alone found the target in 120 queries; current sgrep alone did so in 30. sgrep had lower measured latency and required no corpus index.

Hit@k counts the labeled snippet among the first k distinct returned files. Repeated chunks occupy one rank. MRR@10 is reciprocal rank truncated at ten, with zero for a miss or error; it is **not** the original paper's full-corpus MRR. Results identify snippets, not source coverage within a token budget, so they are not directly comparable with the older RepoQA numbers below.

Every tool sees the same original code, including docstrings, in opaque hash-named files. Queries, labels, and logs remain outside the search directory. CK's empty `.ckignore` prevents generated comment text entering lexical retrieval. Native index inspection confirmed all 6,267 snippets: CK BM25 additionally stores that empty configuration document. Source hashes and returned paths are checked; malformed results and subprocess failures stay in the denominator.

### Conditions and limitations

- **sgrep:** starting `main` at `9594adc` and current `main` at `973b010`, both using Potion Code 16M v2 and `--model code --json -n 100`. The newer revision uses live hybrid score fusion. Retrieval implementation and dependencies are unchanged in this benchmark PR.
- **CK 0.7.11:** semantic mode uses `bge-small`; lexical mode uses its native BM25 search. Both use `--jsonl --full-section --threshold 0 --topk 100` and receive the original query unchanged. Native query-parser errors, including apostrophes in English queries, count as failures.
- **ripgrep:** case-insensitive literal OR of fixed sgrep-style query words, returning filenames in path order. This is a simple control, not an agent choosing targeted grep commands.
- **Timing:** 500 sequential fresh native CLI calls per method. The original four methods rotate order per query; current sgrep is a separate sequential phase after that comparison, so its latency comparison is less controlled. CLI startup and model loading are included; harness parsing is excluded. A separate development query warms each method. Models were cached, filesystem caches were not flushed, and background host load was not controlled. Apple M5 Max, 48 GiB RAM.
- **Setup:** CK's initial semantic index took 122.6s and 13.1 MB. Combined indexes after BM25 warmup/search used 15.6 MB. The first BM25 call took 0.337s, including lexical index construction; it is retained separately from query timings. sgrep and ripgrep need no corpus index.
- **Scope:** Python snippets totaling 1.93 MB, not complete repositories or large monorepos. CoSQA labels one answer per query, so valid alternatives can be undercredited. Pretrained-model overlap with this public dataset is unaudited. Jevgrep was not rerun on CoSQA.

### Evidence and reproduction

[cosqa-results.json](cosqa-results.json) contains aggregate and per-query scores, dataset/binary provenance, and raw-record hashes. [cosqa-protocol.json](cosqa-protocol.json) freezes the methodology. The stdlib-only [runner](cosqa.py) preserves every CLI invocation, stdout, stderr, timing, and error, and can regenerate scores without rerunning search. It refuses changed corpora, leaked metadata, and overwritten runs.

The code model/parser must already be cached for offline sgrep runs. Install ripgrep, then run from this repository:

```bash
COSQA_WORK="$(mktemp -d)"
git clone https://github.com/Jun-jie-Huang/CoCLR.git "$COSQA_WORK/upstream"
git -C "$COSQA_WORK/upstream" checkout 14ebcacf9e9bc3e7109102632bc63047876f27d2
npm install --prefix "$COSQA_WORK/tools" @beaconbay/ck-search@0.7.11
COSQA_CK="$COSQA_WORK/tools/node_modules/@beaconbay/ck-search/dist/bin/ck"
git clone https://github.com/context-dot-dev/sgrep.git "$COSQA_WORK/sgrep"
git -C "$COSQA_WORK/sgrep" checkout 9594adce03b5825bc9e8c617072a00878df45ed4
cargo build --release --locked --manifest-path "$COSQA_WORK/sgrep/Cargo.toml"
COSQA_SG="$COSQA_WORK/sgrep/target/release/sgrep"
python3 benchmarks/cosqa.py prepare --upstream "$COSQA_WORK/upstream" --output "$COSQA_WORK/run"
python3 benchmarks/cosqa.py index --output "$COSQA_WORK/run" --sgrep "$COSQA_SG" --ck "$COSQA_CK"
python3 benchmarks/cosqa.py run --output "$COSQA_WORK/run" --sgrep "$COSQA_SG" --ck "$COSQA_CK"
git -C "$COSQA_WORK/sgrep" checkout 973b01035968975ffaba7e6b428aaf636fffbaa6
cargo build --release --locked --manifest-path "$COSQA_WORK/sgrep/Cargo.toml"
python3 benchmarks/cosqa.py add-sgrep --output "$COSQA_WORK/run" --sgrep "$COSQA_SG" --ck "$COSQA_CK" --sgrep-commit 973b01035968975ffaba7e6b428aaf636fffbaa6
python3 benchmarks/cosqa.py score --output "$COSQA_WORK/run"
```

Raw outputs and interrupted diagnostics are retained in the local evidence directory, not hosted in this repository. The commands above create an equivalent evidence directory on another machine. Regenerate the chart with `uv run --with matplotlib python benchmarks/plot_cosqa.py`.

## Live hybrid fusion: before and after

On October 9, 2026, the new pipeline was compared with `origin/main` at `849a91c` on all **600 questions across 60 repositories and six languages** in the local RepoQA release2024-06-23 suite. Both versions use current code-aware chunking. This is a retrieval adaptation, not an official RepoQA model score.

| Metric | Before | After |
| --- | ---: | ---: |
| File@1 | 384/600 (64.0%) | 398/600 (66.3%) |
| File@10 | 564/600 (94.0%) | 566/600 (94.3%) |
| Half function@2k | 431/600 (71.8%) | 455/600 (75.8%) |
| Half function@8k | 507/600 (84.5%) | 533/600 (88.8%) |
| Complete function@8k | 507/600 (84.5%) | 533/600 (88.8%) |
| Median CLI latency | 80.7 ms | 68.9 ms |
| p95 CLI latency | 124.0 ms | 123.4 ms |

There were **32 complete-function gains and six losses**, and 31 file@1 gains versus 17 losses. All six lost function targets remain in the output but move beyond the 8k source-token budget. TypeScript complete-function coverage fell from 90% to 89%; the other language totals improved or stayed equal. No weights or thresholds were tuned against these questions.

The change combines corpus-wide BM25, equal-weight relative score fusion, complete static embeddings without padding/truncation, and retention of unique overlapping source. This measures the combined change, not score fusion in isolation. Optional agent-supplied ripgrep matches are covered by real CLI checks and are not used in this natural-language-only benchmark.

Both binaries use `--model code --json -n 50`. Returned source and corpus hashes are verified; source lines are deduplicated before applying the same 2,000/8,000 o200k token budgets. All 600 queries completed for both versions. Latency is measured separately with the existing 12-query panel, repeated three times per version in alternating order. Model and parser downloads are cached; filesystem caches are not cleared. Hardware: Apple M5 Max. These source snapshots do not establish cold-start or large-monorepo performance; the dataset was previously used and model training overlap is unaudited.

On the same 60-query subset used below, the current before/after comparison is 34/60 → 39/60 file@1 and 52/60 → 58/60 complete-function@8k. [hybrid-results.json](hybrid-results.json) retains all 600 paired scores, per-language results, source/binary provenance, record hashes, and the six regressions. The local full-output receipt and replay runner are in `artifacts/sgrep-hybrid-fusion-20261009` in the Context workspace; those paths require adjustment on another machine.

## Published v0.2.0 tool comparison

![Code-search accuracy and latency](benchmark.svg)

This is a retrieval adaptation of [RepoQA](https://github.com/evalplus/repoqa), evaluated on October 6, 2026. A fixed sample contains 60 function-description queries across 12 repositories and six languages: C++, Go, Java, Python, Rust, and TypeScript. It represents 10% of the 600-query release dated June 23, 2024, rather than an official RepoQA leaderboard score.

## Results

| Tool | File@1 | File@10 | Function@8k | Complete function@8k | Median | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sgrep | 53.3% | 91.7% | 76.7% | 66.7% | 71 ms | 91 ms |
| ripgrep | 0.0% | 16.7% | 15.0% | 1.7% | 23 ms | 41 ms |
| CK | 43.3% | 80.0% | 76.7% | 75.0% | 226 ms | 297 ms |
| Jevgrep | 75.0% | 80.0% | 60.0% | 60.0% | 10,183 ms | 16,965 ms |

File@1 and File@10 measure whether the target file appears within the first one or ten distinct files. Function@8k requires at least half the target function's lines within 8,000 o200k source tokens; complete-function coverage requires every line. Source lines are deduplicated in result order and verified against the snapshots.

Jevgrep has the best first-file accuracy. Its Java results often provide declaration locations without source excerpts, which score zero on source coverage even when the file is correct. CK and sgrep tie on half-function coverage, while CK returns complete functions more often. Ripgrep receives literal query words and returns matching lines in path order; this does not measure an agent constructing targeted grep commands.

## Conditions

Quality uses all 60 queries. Median and p95 latency come from a separate sequential replay of 12 queries, one per repository, after indexing and quality runs finish. All searches completed. The host was an Apple M5 Max with 48 GiB of memory; model downloads were cached and filesystem caches were not cleared.

- **sgrep v0.2.0** uses Potion Code 16M v2, `-n 50 --json`, and a fresh process with model loading included. The general-text model added in v0.3.0 is not evaluated here.
- **CK v0.7.11** uses bge-small with `--sem --full-section --threshold 0 --topk 50`. Building its indexes took 411 seconds and 54.7 MB, excluded from search latency.
- **dzhng/jevgrep at `703aba1`** uses its native retrieval core with TypeSafe `jev-1.13.0`, concurrency 32, default rate budgeting, and no answer cache. Its resident Bun adapter excludes CLI startup. Timing covers the full retrieval pipeline, not a single model request.
- **ripgrep** uses case-insensitive literal OR matching of the same query words as sgrep, with `--sort path` and matching lines only.

Repositories and questions were selected by a fixed hash before scoring, with no subsequent tuning. The supplied snapshots total 12 MB, so these results do not establish large-monorepo performance. Python queries were previously available, and public-model training overlap has not been audited.

## Evidence and reproduction

[results.json](results.json) contains aggregate and per-query scores, the protocol, and record hashes. The [recorded-output archive](https://github.com/mrmps/sgrep/releases/download/v0.2.0/benchmark-evidence.tar.gz) includes queries, source manifests, native Jev output, runners, and reproduction instructions. The original runners retain machine-specific paths that must be adjusted for another host. Use the pinned RepoQA source snapshots rather than current repository checkouts.

To regenerate this graphic, install `matplotlib` and run `python benchmarks/plot.py`. The figure reads the checked-in results and includes Context's vector wordmark.

The [v0.2.0 verification receipt](https://github.com/mrmps/sgrep/releases/download/v0.2.0/verification.json) also records the separate Python-to-Rust comparison: median 397 → 74 ms, p95 834 → 129 ms, with all 100 ranked result lists unchanged.
