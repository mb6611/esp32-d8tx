#!/bin/bash
# Clone Betaflight at the locked commit and install the hash-verified toolchain into work/.
# Usage: fetch.sh [--toolchain-tarball PATH]   (idempotent; any hash mismatch is fatal)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/SOURCES.lock"
WORK="$HERE/work"
TARBALL_SRC=""; LINUX_TARBALL_SRC=""; BF_MIRROR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --toolchain-tarball) TARBALL_SRC="$2"; shift 2;;
    --linux-toolchain-tarball) LINUX_TARBALL_SRC="$2"; shift 2;;
    --bf-mirror) BF_MIRROR="$2"; shift 2;;   # local git dir used instead of BF_URL (read only; commit still verified)
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
mkdir -p "$WORK/downloads" "$WORK/tools"

# --- Betaflight clone
if [ ! -d "$WORK/betaflight/.git" ]; then
  git clone --no-checkout "${BF_MIRROR:-$BF_URL}" "$WORK/betaflight"
fi
if [ "$(git -C "$WORK/betaflight" rev-parse --verify -q HEAD 2>/dev/null || true)" != "$BF_COMMIT" ]; then
  git -C "$WORK/betaflight" cat-file -e "$BF_COMMIT^{commit}" 2>/dev/null || git -C "$WORK/betaflight" fetch origin tag "$BF_TAG"
  git -C "$WORK/betaflight" checkout -q --detach "$BF_COMMIT"
fi
HEAD_NOW="$(git -C "$WORK/betaflight" rev-parse HEAD)"
[ "$HEAD_NOW" = "$BF_COMMIT" ] || { echo "FATAL: HEAD $HEAD_NOW != lock $BF_COMMIT" >&2; exit 1; }
TAGC="$(git -C "$WORK/betaflight" rev-parse -q --verify "refs/tags/$BF_TAG^{commit}" 2>/dev/null || true)"
if [ -n "$TAGC" ] && [ "$TAGC" != "$BF_COMMIT" ]; then echo "FATAL: tag $BF_TAG -> $TAGC != lock" >&2; exit 1; fi

# --- Toolchain tarball
TB="$WORK/downloads/$TOOLCHAIN_FILE"
if [ -n "$TARBALL_SRC" ]; then
  [ "$(sha "$TARBALL_SRC")" = "$TOOLCHAIN_SHA256" ] || { echo "FATAL: --toolchain-tarball sha256 mismatch" >&2; exit 1; }
  [ -f "$TB" ] && [ "$(sha "$TB")" = "$TOOLCHAIN_SHA256" ] || cp "$TARBALL_SRC" "$TB"
fi
if [ ! -f "$TB" ]; then curl -L -o "$TB.part" "$TOOLCHAIN_URL" && mv "$TB.part" "$TB"; fi
[ "$(sha "$TB")" = "$TOOLCHAIN_SHA256" ] || { echo "FATAL: toolchain sha256 mismatch" >&2; rm -f "$TB"; exit 1; }
if [ ! -x "$WORK/tools/$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc-9.2.1" ]; then
  rm -rf "$WORK/tools/$TOOLCHAIN_DIR"
  tar -C "$WORK/tools" -xjf "$TB"
fi
LTB="$WORK/downloads/$LINUX_TOOLCHAIN_FILE"
if [ -n "$LINUX_TARBALL_SRC" ]; then
  [ "$(sha "$LINUX_TARBALL_SRC")" = "$LINUX_TOOLCHAIN_SHA256" ] || { echo "FATAL: --linux-toolchain-tarball sha256 mismatch" >&2; exit 1; }
  [ -f "$LTB" ] && [ "$(sha "$LTB")" = "$LINUX_TOOLCHAIN_SHA256" ] || cp "$LINUX_TARBALL_SRC" "$LTB"
fi
if [ ! -f "$LTB" ]; then curl -L -o "$LTB.part" "$LINUX_TOOLCHAIN_URL" && mv "$LTB.part" "$LTB"; fi
[ "$(sha "$LTB")" = "$LINUX_TOOLCHAIN_SHA256" ] || { echo "FATAL: linux toolchain sha256 mismatch" >&2; rm -f "$LTB"; exit 1; }
"$WORK/tools/$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc" --version | head -1
echo "fetch OK: betaflight $BF_COMMIT, toolchain sha256 $TOOLCHAIN_SHA256"
