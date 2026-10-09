# sgrep

**Search code and documents with ripgrep and local static embeddings.**

sgrep finds files that match your query, then ranks relevant passages by meaning. It runs on your machine and reads fresh source on every search, so there is no index to build or keep in sync.

[Benchmarks](#benchmarks) · [Releases](https://github.com/mrmps/sgrep/releases) · [Context.dev](https://context.dev)

## Benchmarks

![Code-search benchmark comparing function retrieval and median latency for sgrep, CK, Jevgrep, and ripgrep.](benchmarks/benchmark.svg)

On this code-search sample, sgrep matched CK's 76.7% function-retrieval rate at 71 ms median latency, without a source index. Jevgrep was best at ranking the correct file first, while CK returned complete functions more often. These results cover small source snapshots, not large monorepos or general-document retrieval.

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

The default `--model auto` uses general-text embeddings when every shortlisted candidate is a prose file (`.md`, `.mdx`, `.txt`, `.rst`, `.adoc`, `.org`, or `.text`, case-insensitive). Code, mixed candidates, and other file types use code embeddings. You can choose explicitly when a file extension does not reflect its contents:

```sh
sgrep "how do refunds work" . --model text
sgrep "retry with exponential backoff" . --model code
```

Each model downloads about 32–34 MB on first use and works offline afterward. Code search also downloads and caches the required Tree-sitter grammars on first use. Your source and queries stay local. Existing Hugging Face caches are reused, and `HF_HUB_OFFLINE=1` prevents downloads.

Directory searches follow ripgrep's ignore rules and skip hidden and binary files. Results include relative paths, one-based line ranges, and source. Exit codes are `0` for results, `1` for no matches, and `2` for errors.

## How it works

Ripgrep finds files containing query words, and Rust processes those files in parallel. Code uses a Rust port of Chonkie 1.7.0 CodeChunker with the exact boundary algorithm from Tree-sitter language-pack 1.21.0, the same pinned grammars, character tokenizer, and 2,048-character size estimate. It skips metadata that CodeChunker discards and avoids parsing files that already fit in one chunk. Supported extensions cover Python, C/C++, Go, Java, Rust, JavaScript/JSX, and TypeScript/TSX. Other files use Rust Chonkie RecursiveChunker with a 2,048-character target. Chunk boundaries expand to whole source lines, so a long line can exceed that target. BM25 selects 200 candidates, static embeddings rank their meaning, and reciprocal rank fusion combines the two rankings before removing overlapping results. Files without query-word matches cannot be recovered by the semantic step.

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
```

The end-to-end checks use the real models and write a JSON receipt. To compare two executables on your own queries, run `python3 tests/benchmark.py BEFORE AFTER queries.json results`. Each query is an object with `id`, `query`, and an absolute `root` path.

[MIT](LICENSE) · A [Context.dev](https://context.dev) project, built on Minish Lab's static embeddings.
