# sgrep

Search code with ripgrep and static code embeddings. No index, server, or API key.

```sh
brew install ripgrep # or your package manager
cargo install --git https://github.com/mrmps/sgrep --locked
sgrep "where do we retry failed requests" ./src
sgrep "parse config file" . -n 3 --json
```

Requires Rust 1.90+ to build. The installed executable needs only ripgrep;
there is no Python runtime. This replaces the earlier Python package: remove
that installation with `uv tool uninstall sgrep` (or `pip uninstall sgrep`) first.

Ripgrep finds files containing query words. Files are processed in parallel.
Python functions become chunks;
other text uses windows of up to 120 lines. BM25 selects 200 candidates.
[Potion Code 16M v2](https://huggingface.co/minishlab/potion-code-16M-v2)
embeds them locally, then reciprocal rank fusion combines lexical and semantic
ranks. Overlapping results are removed.

The first matching search downloads about 34 MB of model files from Hugging Face.
After that, searches work offline. Only model weights are cached; source files
are read and embedded on each search. Code and queries stay on your machine.
Each CLI invocation loads the model. Existing Hugging Face model caches are
reused (`HF_HOME` / `HF_HUB_CACHE`); `HF_HUB_OFFLINE=1` prevents downloads.

Directory searches follow ripgrep's ignore rules and skip hidden/binary files.
Results include paths relative to the searched directory (or the searched file's
parent), one-based line ranges, and source. Exit codes: `0` results, `1` none,
`2` error. Semantic ranking cannot recover files with no query-word matches.

## Develop

```sh
cargo build --release --locked
PATH="$PWD/target/release:$PATH" python3 tests/e2e.py > e2e-results.json
```

The end-to-end check runs the installed CLI with the real model and writes a JSON
receipt. It needs ripgrep and internet for the first model download.

To compare CLI speed and ranked output against another version:

```sh
python3 tests/benchmark.py /path/to/before /path/to/after queries.json results
```

`queries.json` is an array of `{ "id": "example-00", "query": "...", "root": "/path/to/repo" }`.
Python scripts are also accepted as baselines. Every timed search starts a new
process; result pairs and timings are saved in `results/`.

## Speed

Against Python v0.1 (`5c264b8`), 100 RepoQA Python searches on an M5 Max / 48 GB:

| Fresh CLI process, cached model | Python | Rust |
| --- | ---: | ---: |
| Median | 397 ms | 74 ms |
| p95 | 834 ms | 129 ms |

All 100 ranked result lists matched exactly (`-n 200 --json`). Methods alternated,
filesystem caches were not cleared, and model loading was included. This measures
small repository snapshots, not large monorepos. No daemon or source index.
