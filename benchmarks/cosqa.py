"""Run CoSQA's complete retrieval test split against real search CLIs.

Failure contract (fixed before implementation): reject mismatched labels, query
leakage, changing corpora/binaries, duplicate ranks, invalid paths and malformed
output. Keep failed searches in the denominator. Separate indexing from search;
report truncated MRR honestly. Retain native output for independent score replay.
Only Python's standard library is required. See README.md for reproduction.
"""

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

UPSTREAM = "14ebcacf9e9bc3e7109102632bc63047876f27d2"
METHODS = ("sgrep", "ck-sem", "ck-lex", "ripgrep")
STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "not",
    "of",
    "on",
    "or",
    "our",
    "should",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "to",
    "use",
    "using",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
    "function",
    "description",
    "purpose",
    "input",
    "output",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read(path):
    return json.loads(path.read_text())


def process(command, cwd, timeout=120):
    start = time.perf_counter()
    try:
        p = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={**os.environ, "HF_HUB_OFFLINE": "1"},
        )
        return {
            "argv": command,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
            "seconds": time.perf_counter() - start,
        }
    except subprocess.TimeoutExpired as e:

        def decode(value):
            return (
                value.decode("utf-8", errors="replace")
                if isinstance(value, bytes)
                else value or ""
            )

        return {
            "argv": command,
            "returncode": None,
            "stdout": decode(e.stdout),
            "stderr": decode(e.stderr),
            "seconds": time.perf_counter() - start,
            "error": f"timeout after {timeout}s",
        }


def prepare(args):
    root = args.output / "corpus"
    if root.exists():
        raise ValueError("Use a new output directory; corpus already exists")
    protocol = read(Path(__file__).with_name("cosqa-protocol.json"))
    if (args.output / "protocol.json").exists() and read(
        args.output / "protocol.json"
    ) != protocol:
        raise ValueError("Output directory has a different protocol")
    upstream = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.upstream, text=True
    ).strip()
    if upstream != UPSTREAM:
        raise ValueError(f"Expected CoCLR {UPSTREAM}, got {upstream}")
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", "data/search"],
        cwd=args.upstream,
        check=True,
        capture_output=True,
    )
    data = args.upstream / "data/search"
    code_map = read(data / "code_idx_map.txt")
    queries = read(data / "cosqa-retrieval-test-500.json")
    dev = read(data / "cosqa-retrieval-dev-500.json")[:1]
    if len(code_map) != 6267 or len(queries) != 500:
        raise ValueError("Expected 6267 snippets and 500 test queries")
    if len(set(code_map.values())) != len(code_map) or len(
        {q["idx"] for q in queries}
    ) != len(queries):
        raise ValueError("Duplicate code or query IDs")
    for q in queries + dev:
        if (
            q["label"] != 1
            or code_map.get(q["code"]) != q["retrieval_idx"]
            or not q["doc"].strip()
        ):
            raise ValueError(f"Invalid query/label: {q['idx']}")
    manifest = {}
    root.mkdir(parents=True)
    (root / ".ckignore").write_bytes(b"")
    for code, code_id in code_map.items():
        raw = code.encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        name = f"c_{sha[:24]}.py"
        if name in manifest:
            raise ValueError("Filename collision")
        (root / name).write_bytes(raw)
        manifest[name] = {"code_id": code_id, "sha256": sha, "bytes": len(raw)}

    def normalize(q):
        return {"id": q["idx"], "query": q["doc"], "gold": q["retrieval_idx"]}

    save(args.output / "queries.json", [normalize(q) for q in queries])
    save(args.output / "warmup.json", [normalize(q) for q in dev])
    save(args.output / "manifest.json", manifest)
    save(args.output / "protocol.json", protocol)
    save(
        args.output / "dataset.json",
        {
            "upstream_commit": upstream,
            "files": {
                name: digest(data / name)
                for name in (
                    "code_idx_map.txt",
                    "cosqa-retrieval-test-500.json",
                    "cosqa-retrieval-dev-500.json",
                )
            },
            "queries": 500,
            "snippets": 6267,
            "corpus_bytes": sum(v["bytes"] for v in manifest.values()),
        },
    )
    verify_corpus(args.output)


def verify_corpus(output):
    root = output / "corpus"
    manifest = read(output / "manifest.json")
    if (root / ".ckignore").read_bytes():
        raise ValueError("CK config must stay empty to avoid lexical metadata leakage")
    actual = {p.name for p in root.iterdir() if not p.name.startswith(".")}
    if actual != set(manifest):
        raise ValueError("Corpus membership changed or metadata leaked into corpus")
    for name, meta in manifest.items():
        if digest(root / name) != meta["sha256"]:
            raise ValueError(f"Corpus changed: {name}")
    return manifest


def tools(args):
    result = {}
    for name in ("sgrep", "ck", "rg"):
        supplied = getattr(args, name)
        path = shutil.which(supplied)
        if not path:
            raise ValueError(f"Executable not found: {supplied}")
        result[name] = str(Path(path).absolute())
    return result


def index(args):
    verify_corpus(args.output)
    binary = tools(args)["ck"]
    if (args.output / "corpus/.ck").exists():
        raise ValueError("Refusing to report a reused index as a fresh build")
    record = process(
        [binary, "--index", "--model", "bge-small", "."],
        args.output / "corpus",
        timeout=1800,
    )
    record["persistent_bytes"] = sum(
        p.stat().st_size for p in (args.output / "corpus/.ck").rglob("*") if p.is_file()
    )
    save(args.output / "index.json", record)
    if record["returncode"] != 0 or not record["persistent_bytes"]:
        raise ValueError("CK index failed; see index.json")
    verify_corpus(args.output)
    print(
        json.dumps(
            {k: record[k] for k in ("seconds", "persistent_bytes", "returncode")}
        ),
        flush=True,
    )


def command(method, query, binaries):
    if method == "sgrep":
        return [binaries["sgrep"], query, ".", "--model", "code", "--json", "-n", "100"]
    if method.startswith("ck-"):
        return [
            binaries["ck"],
            "--jsonl",
            "--" + method[3:],
            "--full-section",
            "--threshold",
            "0",
            "--topk",
            "100",
            query,
            ".",
        ]
    terms = sorted(
        {
            t
            for t in re.findall(
                r"[^\W_]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", query).lower()
            )
            if len(t) > 1 and t not in STOP
        }
    )
    if not terms:
        raise ValueError("No literal query terms")
    return [
        binaries["rg"],
        "--no-config",
        "-l",
        "--sort",
        "path",
        "-i",
        "-F",
        *[s for t in terms for s in ("-e", t)],
        "--",
        ".",
    ]


def ranking(method, record, root, manifest):
    accepted = (0, 1) if method.startswith("sgrep") or method == "ripgrep" else (0,)
    if record["returncode"] not in accepted:
        raise ValueError(record.get("error", f"exit {record['returncode']}"))
    raw = record["stdout"]
    if method.startswith("sgrep"):
        paths = [b["path"] for b in json.loads(raw)]
    elif method == "ripgrep":
        paths = raw.splitlines()
    else:
        paths = []
        for line in raw.splitlines():
            item = json.loads(line)
            if "path" in item:
                paths.append(item["path"])
            elif item.get("type") == "match":
                paths.append(item["data"]["path"])
            elif item.get("type") not in ("summary", "metadata"):
                raise ValueError(f"Unrecognized CK record: {list(item)}")
    result = []
    for value in paths:
        path = Path(value)
        relative = (
            (path if path.is_absolute() else root / path)
            .resolve()
            .relative_to(root.resolve())
            .as_posix()
        )
        if relative not in manifest:
            raise ValueError(f"Unknown corpus path: {value}")
        code_id = manifest[relative]["code_id"]
        if code_id not in result:
            result.append(code_id)
    return result[:10]


def score(method, query, record, root, manifest):
    error = None
    try:
        order = ranking(method, record, root, manifest)
    except (ValueError, KeyError, TypeError) as e:
        order, error = [], str(e)
    rank = order.index(query["gold"]) + 1 if query["gold"] in order else None
    return {
        "id": query["id"],
        "method": method,
        "status": "error" if error else "complete",
        "error": error,
        "rank": rank,
        "top10": order,
        "seconds": record["seconds"],
    }


def run(args):
    manifest = verify_corpus(args.output)
    binaries = tools(args)
    if not (args.output / "index.json").exists():
        raise ValueError("Build the CK index before running")
    raw_dir = args.output / "raw"
    raw_dir.mkdir()
    provenance = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "runner_sha256": digest(Path(__file__)),
        "files": {
            name: digest(args.output / name)
            for name in (
                "protocol.json",
                "manifest.json",
                "queries.json",
                "warmup.json",
                "dataset.json",
                "index.json",
            )
        },
        "binaries": {
            k: {
                "path": v,
                "sha256": digest(Path(v).resolve()),
                "version": process([v, "--version"], args.output)["stdout"].strip(),
            }
            for k, v in binaries.items()
        },
    }
    save(args.output / "provenance.json", provenance)
    root = args.output / "corpus"
    for q in read(args.output / "warmup.json"):
        for method in METHODS:
            rec = process(command(method, q["query"], binaries), root)
            row = score(method, q, rec, root, manifest)
            save(
                args.output / "warmup" / f"{method}.json", {"record": rec, "score": row}
            )
            if row["status"] != "complete":
                raise ValueError(f"Warmup failed: {method}: {row['error']}")
    lexical = read(root / ".ck/tantivy_index/meta.json")
    semantic = read(root / ".ck/manifest.json")
    if sum(s["max_doc"] for s in lexical["segments"]) != len(manifest) + 1:
        raise ValueError("Expected all snippets plus CK's empty configuration document")
    if {str(Path(p)) for p in semantic["files"]} != set(manifest):
        raise ValueError("CK semantic index does not cover exactly the corpus")
    queries = read(args.output / "queries.json")
    for i, q in enumerate(queries):
        order = METHODS[i % len(METHODS) :] + METHODS[: i % len(METHODS)]
        for method in order:
            rec = process(command(method, q["query"], binaries), root)
            with gzip.open(
                raw_dir / f"{q['id']}.{method}.json.gz", "wt", encoding="utf-8"
            ) as f:
                json.dump(rec, f)
            row = score(method, q, rec, root, manifest)
            if row["status"] != "complete":
                print(json.dumps(row), flush=True)
        if (i + 1) % 25 == 0:
            print(
                f"{i + 1}/{len(queries)} queries completed across {len(METHODS)} methods",
                flush=True,
            )
    verify_corpus(args.output)
    for name, meta in provenance["binaries"].items():
        if digest(Path(meta["path"]).resolve()) != meta["sha256"]:
            raise ValueError(f"Binary changed during run: {name}")
    summarize(args)


def add_sgrep(args):
    manifest = verify_corpus(args.output)
    root = args.output / "corpus"
    if not (args.output / "results.json").exists():
        raise ValueError("Complete the original comparison first")
    if list((args.output / "raw").glob("*.sgrep-main.json.gz")):
        raise ValueError("Additional sgrep records already exist")
    binary = tools(args)["sgrep"]
    sha = digest(Path(binary).resolve())
    provenance = {
        "commit": args.sgrep_commit,
        "path": binary,
        "sha256": sha,
        "runner_sha256": digest(Path(__file__)),
        "timing": "Sequential fresh CLI calls after the four-method run; separate timing phase, same corpus and queries.",
    }
    q = read(args.output / "warmup.json")[0]
    warmup = process(command("sgrep", q["query"], {"sgrep": binary}), root)
    save(args.output / "warmup/sgrep-main.json", warmup)
    if score("sgrep-main", q, warmup, root, manifest)["status"] != "complete":
        raise ValueError("Additional sgrep warmup failed")
    for i, q in enumerate(read(args.output / "queries.json")):
        record = process(command("sgrep", q["query"], {"sgrep": binary}), root)
        file = args.output / "raw" / f"{q['id']}.sgrep-main.json.gz"
        with gzip.open(file, "wt", encoding="utf-8") as f:
            json.dump(record, f)
        if (i + 1) % 50 == 0:
            print(f"{i + 1}/500 additional sgrep queries", flush=True)
    verify_corpus(args.output)
    if digest(Path(binary).resolve()) != sha:
        raise ValueError("Additional sgrep binary changed during run")
    save(args.output / "additional-sgrep.json", provenance)
    summarize(args)


def summarize(args):
    manifest = verify_corpus(args.output)
    provenance = read(args.output / "provenance.json")
    methods = list(METHODS)
    if (args.output / "additional-sgrep.json").exists():
        provenance["additional_sgrep"] = read(args.output / "additional-sgrep.json")
        methods.append("sgrep-main")
    for name, sha in provenance["files"].items():
        if digest(args.output / name) != sha:
            raise ValueError(f"Frozen input changed: {name}")
    queries = read(args.output / "queries.json")
    rows, hashes = [], {}
    for q in queries:
        for method in methods:
            file = args.output / "raw" / f"{q['id']}.{method}.json.gz"
            with gzip.open(file, "rt", encoding="utf-8") as f:
                rec = json.load(f)
            hashes[file.name] = digest(file)
            rows.append(score(method, q, rec, args.output / "corpus", manifest))
    aggregates = {}
    for method in methods:
        group = [r for r in rows if r["method"] == method]
        times = sorted(r["seconds"] * 1000 for r in group)
        aggregates[method] = dict(
            n=len(group),
            errors=sum(r["status"] != "complete" for r in group),
            **{
                f"hit_at_{k}": sum(
                    r["rank"] is not None and r["rank"] <= k for r in group
                )
                for k in (1, 5, 10)
            },
            mrr_at_10=sum(1 / r["rank"] for r in group if r["rank"]) / len(group),
            median_ms=statistics.median(times),
            p95_ms=times[math.ceil(0.95 * len(times)) - 1],
        )
    index_record = read(args.output / "index.json")
    setup = {k: index_record[k] for k in ("seconds", "persistent_bytes", "returncode")}
    setup["persistent_bytes_after_queries"] = sum(
        p.stat().st_size for p in (args.output / "corpus/.ck").rglob("*") if p.is_file()
    )
    setup["warmup_seconds"] = {
        m: read(args.output / "warmup" / f"{m}.json")["record"]["seconds"]
        for m in METHODS
    }
    result = {
        "dataset": read(args.output / "dataset.json"),
        "protocol": read(args.output / "protocol.json"),
        "provenance": provenance,
        "summary": aggregates,
        "index": setup,
        "rows": rows,
        "raw_sha256": hashes,
    }
    save(args.output / "results.json", result)
    print(json.dumps(aggregates, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("prepare", "index", "run", "add-sgrep", "score")
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--sgrep", default="sgrep")
    parser.add_argument("--sgrep-commit")
    parser.add_argument("--ck", default="ck")
    parser.add_argument("--rg", default="rg")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.phase == "prepare" and args.upstream is None:
        parser.error("prepare requires --upstream")
    if args.phase == "add-sgrep" and not args.sgrep_commit:
        parser.error("add-sgrep requires --sgrep-commit for provenance")
    {
        "prepare": prepare,
        "index": index,
        "run": run,
        "add-sgrep": add_sgrep,
        "score": summarize,
    }[args.phase](args)


if __name__ == "__main__":
    main()
