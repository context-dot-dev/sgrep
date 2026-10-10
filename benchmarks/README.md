# Code-search benchmark

## Full retrieval benchmark (October 9, 2026)

600 RepoQA questions. 500 CoSQA questions. sgrep main at `0fbe8e5`, compared with CK, Jevgrep, and ripgrep.

![RepoQA complete-function retrieval and CoSQA top-ten snippet retrieval.](full-suite/overview.svg)

RepoQA measures whether results contain the full target function within 8,000 source tokens. CoSQA measures whether the labeled snippet appears in the first ten results.

## Rank

![Correct results at each rank cutoff on RepoQA and CoSQA.](full-suite/ranking.svg)

On CoSQA, 132 of sgrep's 162 top-ten misses appear at ranks 11–100. Better ranking could help. This does not measure recall before reranking.

## Speed

![Median and p95 search time for local tools.](full-suite/latency.svg)

Measured on an M5 Max with cached models and indexes. Other work on the machine affected timing, especially on CoSQA.
Jevgrep used a hosted model with concurrent requests; its times are not directly comparable.

## Languages

![Complete-function retrieval for each of the six RepoQA languages.](full-suite/languages.svg)

100 questions per language. The target function must fit within 8,000 returned source tokens.

## Method

RepoQA uses all 60 supplied source snapshots. CoSQA uses all 500 test questions and 6,267 Python snippets.
The RepoQA measure adapts the dataset for retrieval; it is not the official code-generation score.
CoSQA has one labeled answer per question, so other valid answers may count as misses.
Both datasets were used during development.

CK lexical rejected all RepoQA queries and six CoSQA queries. These failures count as misses.
Jevgrep ran on RepoQA only; six partial searches remain included.
Ripgrep used a fixed literal-OR query, not patterns chosen by a person or agent.

<details>
<summary>Run details</summary>

- sgrep used `--model code --json`, with up to 50 passages on RepoQA and 100 on CoSQA.
- CK 0.7.11 used `bge-small`, native semantic or lexical search, and `--full-section --threshold 0`.
- Jevgrep used commit `703aba1` and TypeSafe `jev-1.13.0`. It had four query workers, a 180-second timeout, and a 1,000-request cap.
- ripgrep 15.2.0 matched query words without case sensitivity and sorted results by path.
- File ranks count distinct files. Source coverage uses `o200k` tokens and counts overlapping lines once.

Source hashes and returned lines were checked before publication. CK semantic omitted four target-query files; these count as misses.
Thirty Jevgrep searches were repeated after host sleep affected their clocks. All CK lexical searches were repeated after copied indexes were rebuilt.
These fixes did not select queries by score. Original attempts remain in the local evidence archive.

Each local query started a new process. Methods ran in rotating order; the CK lexical rerun ran separately.
The original rotation included another baseline that is omitted here. Full CK index build time was not measured.
See the [protocol](full-suite/protocol.json), [setup and usage](full-suite/setup-summary.json), and [paired comparisons](full-suite/paired-comparisons.json).

</details>

[CSV](full-suite/summary.csv) · [All 5,000 scored runs](full-suite/results.json)

To check the totals and redraw the charts:

```sh
python3 benchmarks/full-suite/verify.py
# Requires matplotlib:
python3 benchmarks/full-suite/plot.py
```

This checks saved scores. It does not rerun the search tools.

[Earlier measurements](https://github.com/context-dot-dev/sgrep/blob/cfb48d90c88cb92363b7b7e1a6403f575dc7dbc5/benchmarks/README.md#historical-measurements) use older builds, samples, and metrics.
