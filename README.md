<p align="center">
  <a href="https://context.dev">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/context-logo-white.svg">
      <img src="assets/context-logo.svg" alt="Context.dev" width="240">
    </picture>
  </a>
</p>

<h1 align="center">sgrep</h1>

<p align="center"><strong>Search code and documents with ripgrep and local static embeddings.</strong></p>

<p align="center">
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="https://github.com/mrmps/sgrep/releases">Releases</a> ·
  <a href="https://context.dev">Context.dev</a>
</p>

sgrep combines live repo-wide BM25 with semantic scores, preserving strong lexical matches as well as meaningful passages. It runs on your machine and reads fresh source on every search, so there is no index to build or keep in sync.

## Benchmarks

![Code-search benchmark comparing function retrieval and median latency for sgrep, CK, Jevgrep, and ripgrep.](benchmarks/benchmark.svg)

The new live hybrid pipeline improved complete-function retrieval from **507/600 to 533/600** on the full local RepoQA retrieval suite, compared with current main. Median CLI latency on the separate replay panel was **81 → 69 ms**. There were 32 function-retrieval gains and six losses; see the [before/after results and limitations](benchmarks/README.md#live-hybrid-fusion-before-and-after).

The chart above is the earlier published v0.2.0 comparison: sgrep matched CK's 76.7% function-retrieval rate at 71 ms median latency on 60 queries. Jevgrep was best at ranking the correct file first, while CK returned complete functions more often. These source-snapshot results do not establish large-monorepo or general-document performance.

See the [full results and methodology](benchmarks/README.md), including the exact metric, per-query scores, setup costs, and limitations. The earlier Rust rewrite reduced median latency from 397 ms to 74 ms while preserving all 100 Python-query rankings.

## Install

```sh
brew install ripgrep # or use your package manager
cargo install --git https://github.com/mrmps/sgrep --locked
```

Building requires Rust 1.90 or later. You can also download a [macOS Apple Silicon binary](https://github.com/mrmps/sgrep/releases/latest). The executable needs ripgrep on your PATH, but no Python runtime or API key.

If you installed the earlier Python package, remove it with `uv tool uninstall sgrep` or `pip uninstall sgrep` first.

## Usage

```sh
sgrep "where do we retry failed requests" ./src
sgrep "how long does delivery take" ./docs
sgrep "parse configuration" . -n 3 --json
```

You can add matches from an independently chosen ripgrep command. Run both commands from the same directory; emitted paths must fall within the sgrep search scope. Ripgrep still controls its regexes, globs, case handling and context:

```sh
rg --json -i -C 12 -e 'single.?flight|in.?flight|coalesc' ./src \
  | sgrep "where do identical concurrent requests share work" ./src --rg-json -
```

`--rg-json FILE` also accepts saved output. These context blocks join the top 200 repo-wide BM25 candidates, even if they contain none of the question's words. Duplicate locations are scored once. Supplemental matches can explicitly include ignored or hidden files; the default BM25 scan still respects ignore rules. Stale source or paths outside the requested scope produce an error. Ripgrep JSON paths are resolved from the current working directory, including when reading saved output.

Use `--json --explain` to inspect raw BM25 and semantic scores, their normalized values, and the final fused score. Existing JSON output is unchanged without `--explain`.

The default `--model auto` uses general-text embeddings when every shortlisted candidate is a prose file (`.md`, `.mdx`, `.txt`, `.rst`, `.adoc`, `.org`, or `.text`, case-insensitive). Code, mixed candidates, and other file types use code embeddings. You can choose explicitly when a file extension does not reflect its contents:

```sh
sgrep "how do refunds work" . --model text
sgrep "retry with exponential backoff" . --model code
```

Each model downloads about 32–34 MB on first use and works offline afterward. Code search also downloads and caches the required Tree-sitter grammars on first use. Your source and queries stay local. Existing Hugging Face caches are reused, and `HF_HUB_OFFLINE=1` prevents downloads.

Directory searches follow ripgrep's ignore rules and skip hidden and binary files. Results include relative paths, one-based line ranges, and source. Exit codes are `0` for results, `1` for no matches, and `2` for errors.

## How it works

Ripgrep enumerates eligible files, and Rust reads and chunks them in parallel. BM25 uses statistics from the whole live corpus rather than files selected by natural-language words. Code uses a Rust port of Chonkie 1.7.0 CodeChunker with the exact boundary algorithm from Tree-sitter language-pack 1.21.0, the same pinned grammars, character tokenizer, and 2,048-character size estimate. It skips metadata that CodeChunker discards and avoids parsing files that already fit in one chunk. Supported extensions cover Python, C/C++, Go, Java, Rust, JavaScript/JSX, and TypeScript/TSX. Other files use Rust Chonkie RecursiveChunker with a 2,048-character target. Chunk boundaries expand to whole source lines, so a long line can exceed that target. BM25 selects up to 200 nonzero-score candidates, then any supplied ripgrep blocks are added independently. Static embeddings score all text in each candidate, with tokenizer padding and truncation disabled.

[Relative score fusion](https://docs.weaviate.io/weaviate/concepts/search/hybrid-search) scales each candidate's BM25 and semantic scores to 0–1 within that candidate pool and averages them equally. This preserves score gaps that rank-only fusion loses: a standout BM25 result can outrank a semantically stronger but lexically weak passage. A flat score distribution contributes zero; ties favor the higher raw BM25 score. This is not a hard pin or a global confidence threshold, and changing the candidate pool can change the normalization. Results wholly contained in an earlier result are omitted; partial overlaps retain their unique source.

There is no corpus embedding index: code with neither lexical evidence nor an explicitly supplied ripgrep match cannot enter the semantic stage.

The embeddings come from **[Minish Lab](https://github.com/MinishLab)**, the team behind [Model2Vec](https://github.com/MinishLab/model2vec): [Potion Code 16M v2](https://huggingface.co/minishlab/potion-code-16M-v2) for code and [Potion Base 8M](https://huggingface.co/minishlab/potion-base-8M) for general English text. Both models are MIT-licensed and pinned to specific revisions.

## Alternatives

| Project | Approach |
| --- | --- |
| [ripgrep](https://github.com/BurntSushi/ripgrep) | Fast literal and regular-expression search when you know what to match. |
| [CK](https://github.com/BeaconBay/ck) | Local semantic and hybrid code search with a persistent index. |
| [Jevgrep](https://github.com/dzhng/jevgrep) | Model-guided repository search using Jev through TypeSafe. |

## Development

```sh
cargo build --release --locked
PATH="$PWD/target/release:$PATH" python3 tests/e2e.py > e2e-results.json
PATH="$PWD/target/release:$PATH" python3 tests/codechunker.py > chunker-results.json
PATH="$PWD/target/release:$PATH" python3 tests/hybrid.py > hybrid-results.json
```

The end-to-end checks use the real models and write a JSON receipt. To compare two executables on your own queries, run `python3 tests/benchmark.py BEFORE AFTER queries.json results`. Each query is an object with `id`, `query`, and an absolute `root` path.

[MIT](LICENSE) · A [Context.dev](https://context.dev) project, built on Minish Lab's static embeddings.
