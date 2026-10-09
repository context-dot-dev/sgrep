# Code-search benchmark

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
