#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: bash tests/linux.sh /path/to/sgrep output-directory\n' >&2
  exit 2
fi

# Preserve a supplied sgrep symlink for the PATH-based acceptance checks.
binary=$(realpath -s -- "$1")
results=$(realpath -m "$2")
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$results/fixtures" "$results/tmp"
export PATH="$(dirname -- "$binary"):$PATH"
export TMPDIR="$results/tmp"
export HF_HUB_CACHE="$results/assets/models"
export TREE_SITTER_LANGUAGE_PACK_CACHE_DIR="$results/assets/parsers"
export SGREP_CACHE_DIR="$results/assets/index"

{
  . /etc/os-release
  printf 'OS: %s\n' "$PRETTY_NAME"
  uname -smr
  getconf GNU_LIBC_VERSION
  python3 --version
  rg --version
  "$binary" --version
  sha256sum "$binary"
} > "$results/platform.txt"

# Existing acceptance checks require cached models and parsers, including on
# their first query. Warm every supported language before disabling downloads.
for extension in py c cpp go java rs ts tsx js jsx; do
  printf 'terminalneedle\n%.0s' {1..200} > "$results/fixtures/example.$extension"
done
printf 'Shipping orders have delivery tracking information.\n' > "$results/fixtures/shipping.txt"
export HF_HUB_OFFLINE=0
"$binary" terminalneedle "$results/fixtures" --model code --no-cache --json > "$results/code-first-run.json"
"$binary" 'shipping delivery' "$results/fixtures/shipping.txt" --model text --no-cache --json > "$results/text-first-run.json"

export HF_HUB_OFFLINE=1
python3 "$repo_root/tests/e2e.py" > "$results/e2e-results.json"
python3 "$repo_root/tests/discovery.py" > "$results/discovery-results.json"
python3 "$repo_root/tests/codechunker.py" > "$results/chunker-results.json"
printf 'Linux CLI checks passed; receipts: %s\n' "$results"
