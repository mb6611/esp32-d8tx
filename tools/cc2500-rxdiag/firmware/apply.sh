#!/bin/bash
# Reset the clone to the locked commit, copy overlay/ over it, apply patches/*.patch in order.
# Always resets first, so a second run cleanly reproduces the same tree (never double-applies).
# Refuses (exit 1) if the clone has uncommitted *tracked* edits that are not exactly our own
# previous application, unless --force is given.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/SOURCES.lock"
BF="$HERE/work/betaflight"
[ -d "$BF/.git" ] || { echo "run fetch.sh first" >&2; exit 1; }
[ "$(git -C "$BF" rev-parse HEAD)" = "$BF_COMMIT" ] || { echo "FATAL: clone HEAD != lock" >&2; exit 1; }
MARK="$BF/.rxdiag_applied"
# State fingerprint: hash of tracked diff + untracked file list. A tree is "ours" only if it matches
# the fingerprint recorded by the previous apply; anything else is a foreign modification -> refuse.
fp() { { git -C "$BF" diff; git -C "$BF" ls-files --others --exclude-standard | grep -v '^\.rxdiag_applied$' | sort; } | shasum -a 256 | awk '{print $1}'; }
DIRTY="$(git -C "$BF" status --porcelain --untracked-files=no)"
if [ -n "$DIRTY" ]; then
  if [ ! -f "$MARK" ] || [ "$(sed -n 2p "$MARK")" != "$(fp)" ]; then
    [ "${1:-}" = "--force" ] || { echo "REFUSED: clone has modifications not made by apply.sh (use --force to discard)" >&2; exit 1; }
  fi
fi
git -C "$BF" reset -q --hard "$BF_COMMIT"
git -C "$BF" clean -fdxq
cp -R "$HERE/overlay/." "$BF/"
shopt -s nullglob
for p in "$HERE"/patches/*.patch; do
  git -C "$BF" apply --check "$p"
  git -C "$BF" apply "$p"
  echo "applied $(basename "$p")"
done
{ echo "$BF_COMMIT"; fp; } > "$MARK"
echo "apply OK"
