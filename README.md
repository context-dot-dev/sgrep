# sgrep

Search code with ripgrep and static code embeddings. No index, server, or API key.

```sh
brew install ripgrep # or your package manager
uv tool install git+https://github.com/mrmps/sgrep
sgrep "where do we retry failed requests" ./src
sgrep "parse config file" . -n 3 --json
```

Python 3.10+. `pip install git+https://github.com/mrmps/sgrep` also works.

Ripgrep finds files containing query words. Python functions become chunks;
other text uses windows of up to 120 lines. BM25 selects 200 candidates.
[Potion Code 16M v2](https://huggingface.co/minishlab/potion-code-16M-v2)
embeds them locally, then reciprocal rank fusion combines lexical and semantic
ranks. Overlapping results are removed.

The first matching search downloads about 34 MB of model files from Hugging Face.
After that, searches work offline. Only model weights are cached; source files
are read and embedded on each search. Code and queries stay on your machine.
Each CLI invocation loads the model, so expect startup overhead.

Directory searches follow ripgrep's ignore rules and skip hidden/binary files.
Results include paths relative to the searched directory (or the searched file's
parent), one-based line ranges, and source. Exit codes: `0` results, `1` none,
`2` error. Semantic ranking cannot recover files with no query-word matches.

## Develop

```sh
uv venv
uv pip install -e .
uv run --no-project python tests/e2e.py > e2e-results.json
```

The end-to-end check runs the installed CLI with the real model and writes a JSON
receipt. It needs ripgrep and internet for the first model download.
