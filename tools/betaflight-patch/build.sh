#!/bin/bash
# Build patched Betaflight 4.2.11 MATEKF411RX (stock flags, LTO, GCC 9.2.1 aarch64-linux in docker ubuntu:24.04).
# Reuses toolchain/download dirs of ../cc2500-rxdiag/firmware. Output: out/<BUILD_ID>/
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RX="$HERE/../cc2500-rxdiag/firmware"
. "$RX/SOURCES.lock"
"$HERE/apply.sh"
BF="$HERE/work/betaflight"
TARGET="${TARGET:-MATEKF411RX}"
BUILD_ID="$(cd "$HERE" && python3 - <<'PY'
import hashlib, glob
h = hashlib.sha256()
for p in sorted(glob.glob("patches/*.patch")) + ["../cc2500-rxdiag/firmware/SOURCES.lock"]:
    h.update(p.encode() + b"\0" + open(p, "rb").read())
print(h.hexdigest()[:8])
PY
)"
echo "BUILD_ID=$BUILD_ID"
OUT="$HERE/out/$BUILD_ID"; rm -rf "$OUT"; mkdir -p "$OUT"
LTOOLS="$RX/work/tools-linux"
[ -x "$LTOOLS/$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc" ] || { mkdir -p "$LTOOLS"; tar xjf "$RX/work/downloads/$LINUX_TOOLCHAIN_FILE" -C "$LTOOLS"; }
echo "$(shasum -a 256 "$RX/work/downloads/$LINUX_TOOLCHAIN_FILE" | cut -d' ' -f1)" | grep -q "$LINUX_TOOLCHAIN_SHA256" || { echo "toolchain sha mismatch" >&2; exit 1; }
rm -rf "$HERE/work/bf-build"; rsync -a --exclude obj --exclude .git "$BF/" "$HERE/work/bf-build/"
docker run --rm -v "$HERE/work":/w -v "$LTOOLS":/tools -w /w/bf-build ubuntu:24.04 bash -c "
  apt-get update -qq >/dev/null && apt-get install -y -qq make python3 git >/dev/null 2>&1
  export PATH=/tools/$TOOLCHAIN_DIR/bin:\$PATH
  make $TARGET TOOLS_DIR=/tools" > "$OUT/build.log" 2>&1 || { tail -40 "$OUT/build.log" >&2; exit 1; }
B="$HERE/work/bf-build/obj"
cp "$B"/betaflight_4.2.11_${TARGET}_*.hex "$B"/betaflight_4.2.11_${TARGET}_*.bin "$OUT/"
cp "$B/main/betaflight_${TARGET}.elf" "$B/main/betaflight_${TARGET}.map" "$OUT/" 2>/dev/null || true
echo "$BUILD_ID" > "$OUT/BUILD_ID"
PATH="$LTOOLS/$TOOLCHAIN_DIR/bin:$PATH"
( cd "$OUT" && shasum -a 256 *.hex *.bin BUILD_ID > SHA256SUMS )
grep -c "warning:" "$OUT/build.log" | sed 's/^/warnings in log: /' | tee "$OUT/warnings.txt"
ls -l "$OUT"/*.bin | tee "$OUT/size.txt"
echo "build OK: $OUT"
