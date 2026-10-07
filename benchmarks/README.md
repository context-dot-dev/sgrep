# Code-search benchmark

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
