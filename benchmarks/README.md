# Code-search benchmark

## Indexed discovery latency (October 9)

Warm Context searches now reuse chunks, lexical postings, and vectors without changing ranking. The final release was measured on the same 2,545-file, 85.8 MB snapshot, with cached models, fresh CLI processes, alternating arms, and no concurrent build/test jobs. Times include process startup and JSON serialization. The piped row includes ripgrep execution.

| Workload | Before | Indexed candidate |
| --- | ---: | ---: |
| Context discovery, target `main` (`973b010`), paired median | 456.9 ms | 62.5 ms |
| Context discovery, previous PR implementation (`aba33ff`), four per-query warm medians | 516–526 ms | 60.8–61.9 ms |
| Ripgrep → stdin reranking, previous PR implementation, warm median | 96.5 ms | 42.6 ms |
| First Context search with empty corpus cache, models cached | 2.78 s | 3.54 s |

The target-main comparison uses 20 paired calls across four questions; main does not support `--stdin`. The optimization comparison uses eight pairs per case, with the first pair reported separately: the slowest warm discovery call was 64.1 ms, and the slowest piped call was 44.7 ms. All 40 optimization pairs matched byte for byte, including scores. All 60 frozen RepoQA queries returned exactly the same top-50 results before and after optimization (39/60 correct-file@1, 52/60 complete-function within 8,000 characters). This preserves existing retrieval quality; it does not fix the four Context deciding-line misses described below.

The Context index is 257 MB (245 MiB) and contains source passages. Changed files trigger a full scope rebuild; cold and post-edit searches are not under 80 ms. Unix validation relies on file size, inode, modification time and change time, with a fresh ripgrep file listing; other platforms hash source too. These are local measurements, not a latency guarantee across repositories, filesystems, or machines. Raw timings, binary hashes, and conditions are in [index-results.json](index-results.json).

Reproduce paired timing and exact-output checks with:

```sh
HF_HUB_OFFLINE=1 SGREP_CACHE_DIR=/tmp/sgrep-index-bench \
  python3 tests/latency.py BEFORE AFTER cases.json results.json --repeats 8
```

Each case contains `name`, `cwd`, and `args`; add `input_command` for a producer such as `rg --json -C 3 ...`. Case definitions are retained in the result file; replace the snapshot-root placeholder with your local checkout. Use `aba33ff` for the exact-parity baseline, since independent discovery intentionally differs from target main. The earlier discovery measurements below predate this index optimization.

## Discovery and piped reranking (October 9)

The immediate target is now `973b010`, after the hybrid-fusion prerequisite merged as PR #3. Its executable sources are identical to the measured parent `6579a74`. The independent discovery/stdin change has this result on the same fixed 60 cases:

| Metric | Current main | Discovery/stdin |
| --- | ---: | ---: |
| Correct file in first passage | 39/60 | 39/60 |
| Correct file within five passages | 57/60 | 58/60 |
| At least half the target function within 8,000 characters | 51/60 | 53/60 |
| Complete target function within 8,000 characters | 51/60 | 52/60 |
| Cached median, isolated ABBA panel | 67.7 ms | 56.7 ms |
| First query per corpus median, model already cached | 69.1 ms | 103.8 ms |

The table below retains the cumulative comparison with the main version at the start of this task; its gains include the prerequisite and should not all be attributed to semantic discovery. Both comparisons and paired regressions are in [discovery-results.json](discovery-results.json).

This paired comparison uses the same 60 frozen queries and source snapshots, with `849a91c` as the baseline. The subsequent `9594adc` main commit changes only README/logo assets. No query-specific tuning was applied to this panel. Both executables return up to 50 source passages; every returned range was checked against the snapshot.

| Metric | Before | After |
| --- | ---: | ---: |
| Correct file in first passage | 34/60 (56.7%) | 39/60 (65.0%) |
| Correct file within five passages | 57/60 (95.0%) | 58/60 (96.7%) |
| At least half the target function within 8,000 characters | 48/60 (80.0%) | 53/60 (88.3%) |
| Complete target function within 8,000 characters | 48/60 (80.0%) | 52/60 (86.7%) |
| Cached query median, isolated ABBA panel | 76.6 ms | 56.8 ms |
| First query per corpus median, model already cached | 72.3 ms | 98.7 ms |

The coverage budget includes paths and complete source lines, measured in Unicode characters, **not the token budget in the older comparison below**. File ranks count passages, not distinct files. The latency panel runs one fixed query per repository twice per executable, in ABBA order, with fresh processes and cached models/corpus vectors. First-corpus timings are retained from the quality run and are less controlled; compilation overlapped part of that run. The candidate uses 12.5 MB of corpus-vector caches across the 12 snapshots. These caches are additional to model weights.

On the four previously investigated Context questions, whole-repository discovery still returned none of the four deciding lines in its top five, before or after. Targeted `rg --json -C 3 ... | sgrep ... --stdin` returned three of four. Those regexes came from prior source inspection, so this is an assisted workflow example, not a blind discovery score. On the 85.8 MB Context snapshot, the first candidate search took 3.3 seconds; subsequent searches took roughly 0.5–0.7 seconds, versus 0.35–0.44 seconds before. Piped reranking took roughly 90–115 ms including ripgrep.

The change enables retrieval without lexical overlap and useful piped reranking; it does not establish reliable reasoning about code conditions. The sample is small, previously published, and not newly held out. [Measurements and conditions](discovery-results.json) retain paired regressions as well as gains. The CLI runner retains every output and validates its source ranges:

```sh
python3 tests/retrieval_benchmark.py BEFORE AFTER queries.json /tmp/sgrep-comparison
```

Use the frozen query file from the evidence archive below (update its corpus paths for your host). Each query includes `id`, `query`, `root`, and `target: {path, start, end}`. The runner reports first-corpus and reuse timings separately; use an empty output directory for first-encoding measurements.


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
