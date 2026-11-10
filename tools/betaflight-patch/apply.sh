#!/bin/bash
# Create/reset a CLEAN Betaflight 4.2.11 tree in work/betaflight and apply patches/*.patch.
# Never touches tools/cc2500-rxdiag/firmware/work/betaflight (only used as a local clone source).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RX="$HERE/../cc2500-rxdiag/firmware"
. "$RX/SOURCES.lock"
BF="$HERE/work/betaflight"
mkdir -p "$HERE/work"
if [ ! -d "$BF/.git" ]; then
  SRC="$BF_URL"; [ -d "$RX/work/betaflight/.git" ] && SRC="$RX/work/betaflight"
  git clone -q --no-checkout "$SRC" "$BF"
fi
git -C "$BF" checkout -q -f "$BF_COMMIT"
git -C "$BF" reset -q --hard "$BF_COMMIT"
git -C "$BF" clean -fdxq
[ "$(git -C "$BF" rev-parse HEAD)" = "$BF_COMMIT" ] || { echo "HEAD != lock" >&2; exit 1; }
shopt -s nullglob
for p in "$HERE"/patches/*.patch; do
  git -C "$BF" apply --check "$p"; git -C "$BF" apply "$p"; echo "applied $(basename "$p")"
done
echo "apply OK"
