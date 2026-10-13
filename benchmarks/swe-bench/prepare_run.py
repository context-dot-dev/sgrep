"""Copy the historical harness into a fresh directory with isolated cloud/cache names."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run-id", required=True, help="Unique lowercase name for this study")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.run_id):
        parser.error("run-id must be 1–40 lowercase letters, digits or hyphens")
    source = Path(__file__).resolve().parent / "harness"
    original = json.loads((source / "frozen-manifest.json").read_text())
    for name, expected in original["hashes"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            parser.error(f"Historical source hash mismatch: {name}")
    if args.destination.exists():
        parser.error("destination already exists; choose a new study directory")
    replacements = {
        "sgrep-swe-benchmark-20261012": f"sgrep-swe-{args.run_id}",
        "sgrep-benchmark-tools-20261012": f"sgrep-tools-{args.run_id}",
        "frozen-v4-validated": f"study-{args.run_id}",
        "pilot-v3": f"pilot-{args.run_id}",
    }
    shutil.copytree(source, args.destination, ignore=shutil.ignore_patterns("__pycache__"))
    for path in args.destination.glob("*.py"):
        text = path.read_text()
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text)
    # A historical receipt does not establish that the new environment passed.
    (args.destination / "prepared-agent-controls.json").unlink()
    (args.destination / "rerun.json").write_text(json.dumps({
        "run_id": args.run_id, "namespace_changes": replacements,
        "historical_manifest": "frozen-manifest.json",
        "source_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(args.destination.glob("*.py"))},
    }, indent=2) + "\n")
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
