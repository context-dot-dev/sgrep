"""Ripgrep candidates, ranked with static code embeddings."""
import argparse
import ast
from collections import Counter
from functools import cache
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

MODEL = "minishlab/potion-code-16M-v2"
REVISION = "e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b"
STOP = set("a an and are as at be been but by can do does for from had has have how i if in into is it its me not of on or our should so that the their them there these they this to use using was we what when where which who will with would you your function description purpose input output".split())


def words(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [w for w in re.findall(r"[^\W_]+", text.lower()) if len(w) > 1 and w not in STOP]


def candidates(query, path):
    terms = sorted(set(words(query)))
    root = path if path.is_dir() else path.parent
    command = ["rg", "--no-config", "-l", "-0", "-i", "-F"]
    for term in terms:
        command += ["-e", term]
    result = subprocess.run(command + ["--", "." if path.is_dir() else path.name], cwd=root, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    chunks = []
    for name in sorted(result.stdout.split(b"\0")[:-1]):
        file = root / os.fsdecode(name)
        source = file.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines(keepends=True)
        ranges = []
        if file.suffix == ".py":
            try:
                ranges = [(min([n.lineno] + [d.lineno for d in n.decorator_list]), n.end_lineno)
                          for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            except (SyntaxError, ValueError):
                pass
        gaps, cursor = [], 1
        for start, end in sorted(ranges):
            if start > cursor:
                gaps.append((cursor, start - 1))
            cursor = max(cursor, end + 1)
        if cursor <= len(lines):
            gaps.append((cursor, len(lines)))
        for start, end in sorted(set(ranges + gaps)):
            for first in range(start, end + 1, 100):
                last = min(first + 119, end)
                content = "".join(lines[first - 1:last])
                if set(words(content)).intersection(terms):
                    chunks.append({"path":str(file.relative_to(root)), "start":first, "end":last, "content":content})
                if last == end:
                    break
    return chunks


def bm25(chunks, query):
    counts = [Counter(words(c["path"] + " " + c["content"])) for c in chunks]
    df = Counter(t for c in counts for t in c)
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(counts)
    terms = sorted(set(words(query)))
    scores = [sum(math.log(1 + (len(counts) - df[t] + .5) / (df[t] + .5)) * c[t] * 2.5 /
                  (c[t] + 1.5 * (.25 + .75 * length / average)) for t in terms if c[t])
              for c, length in zip(counts, lengths)]
    return sorted(range(len(chunks)), key=lambda i: -scores[i])


@cache
def model():
    from huggingface_hub import hf_hub_download
    from model2vec import StaticModel

    for filename in ("config.json", "tokenizer.json", "model.safetensors", "README.md"):
        path = hf_hub_download(MODEL, filename, revision=REVISION)
    return StaticModel.from_pretrained(Path(path).parent, normalize=True, quantize_to="float32")


def search(query, path, limit=5):
    chunks = candidates(query, path)
    if not chunks:
        return []
    import numpy as np

    selected = [chunks[i] for i in bm25(chunks, query)[:200]]
    vectors = model().encode([query] + [Path(c["path"]).name + "\n" + c["content"] for c in selected],
                             max_length=None, batch_size=256, use_multiprocessing=False)
    if not np.isfinite(vectors).all():
        raise RuntimeError("embedding model returned non-finite vectors")
    order = np.argsort(-(vectors[1:] @ vectors[0]), kind="stable")
    ranks = np.empty(len(order), dtype=int)
    ranks[order] = np.arange(len(order))
    fused = sorted(range(len(selected)), key=lambda i: -(1 / (61 + i) + 1 / (61 + int(ranks[i]))))
    results = []
    for i in fused:
        chunk = selected[i]
        if any(c["path"] == chunk["path"] and c["start"] <= chunk["end"] and chunk["start"] <= c["end"] for c in results):
            continue
        results.append(chunk)
        if len(results) == limit:
            break
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="natural language or identifiers")
    parser.add_argument("path", nargs="?", default=".", type=Path, help="directory or file (default: .)")
    parser.add_argument("-n", type=int, default=5, metavar="COUNT", help="maximum results (default: 5)")
    parser.add_argument("--json", action="store_true", help="print a JSON array")
    args = parser.parse_args()
    if not words(args.query):
        parser.error("query has no searchable words")
    if args.n < 1:
        parser.error("COUNT must be positive")
    if not args.path.is_file() and not args.path.is_dir():
        parser.error(f"not a file or directory: {args.path}")
    if not shutil.which("rg"):
        parser.error("ripgrep is required; install rg first")
    try:
        results = search(args.query, args.path.resolve(), args.n)
        if args.json:
            print(json.dumps(results, ensure_ascii=False))
        else:
            for c in results:
                print(f'{c["path"]}:{c["start"]}-{c["end"]}\n{c["content"].rstrip()}\n')
    except BrokenPipeError:
        return 0
    except Exception as exc:
        parser.exit(2, f"sgrep: {exc}\n")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
