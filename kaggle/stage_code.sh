#!/usr/bin/env bash
# Stage code + data for Kaggle (ARCHITECTURE.md §9.3).
#   build/sagate-code/   -> Kaggle dataset "<owner>/sagate-code" (tarball + bootstrap.py + GIT_SHA)
#   build/kernels/nbXX/  -> kernel folders with "<owner>" filled in; push these, not kaggle/nbXX
# Usage: bash kaggle/stage_code.sh [--owner <kaggle-username>]
set -euo pipefail
OWNER="prabhashpadhan"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/sagate-code"
KOUT="$ROOT/build/kernels"
rm -rf "$OUT" "$KOUT"
mkdir -p "$OUT" "$KOUT"

SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
git -C "$ROOT" diff --quiet HEAD -- src configs resources || SHA="$SHA-dirty"
echo "$SHA" > "$OUT/GIT_SHA"

# macOS tar otherwise adds ._* AppleDouble files, which Kaggle extracts next to the real configs/resources
export COPYFILE_DISABLE=1
tar -czf "$OUT/sagate-code.tar.gz" --exclude='__pycache__' --exclude='*.pyc' \
    -C "$ROOT" pyproject.toml configs resources src annotations data/processed data/labled-data/synthetic_nl.jsonl \
    -C "$OUT" GIT_SHA
cp "$ROOT/kaggle/bootstrap.py" "$OUT/bootstrap.py"
sed "s/__OWNER__/$OWNER/g" "$ROOT/kaggle/code-dataset/dataset-metadata.json" > "$OUT/dataset-metadata.json"

for d in "$ROOT"/kaggle/nb*/; do
  name="$(basename "$d")"
  mkdir -p "$KOUT/$name"
  cp "$d/run.py" "$KOUT/$name/run.py"
  sed "s/__OWNER__/$OWNER/g" "$d/kernel-metadata.json" > "$KOUT/$name/kernel-metadata.json"
done
echo "staged $SHA for owner $OWNER:"
du -sh "$OUT"/* | sed 's/^/  /'
ls "$KOUT" | sed 's/^/  kernel: /'
