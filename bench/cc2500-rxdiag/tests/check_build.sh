#!/bin/bash
# Gates on a built artifact directory. Usage: check_build.sh [out/<id>]  (default: the only/newest out/<id>)
# Exits non-zero on any violation.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$HERE/../firmware"
. "$FW/SOURCES.lock"
OUT="${1:-}"
if [ -z "$OUT" ]; then OUT="$(ls -dt "$FW"/out/*/ 2>/dev/null | head -1)"; fi
OUT="${OUT%/}"
export PATH="$FW/work/tools/$TOOLCHAIN_DIR/bin:$PATH"
FAILS=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAILS=$((FAILS+1)); }
[ -d "$OUT" ] || { echo "FAIL no output dir"; exit 1; }
ID="$(cat "$OUT/BUILD_ID")"
MAP="$(ls "$OUT"/*.map)"; BIN="$(ls "$OUT"/*.bin)"; ELF="$(ls "$OUT"/*.elf)"

# SHA256SUMS verifies
( cd "$OUT" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1 ) && pass "SHA256SUMS verifies" || fail "SHA256SUMS"

# BUILD_ID recomputed from sources equals the recorded one
NEW="$(cd "$FW" && python3 - <<'PY'
import hashlib, os
files = ["SOURCES.lock"]
for d in ("overlay", "patches"):
    for r, _, fs in os.walk(d):
        for f in fs:
            if f != ".DS_Store": files.append(os.path.join(r, f))
h = hashlib.sha256()
for p in sorted(files): h.update(p.encode() + b"\0" + open(p, "rb").read())
print(h.hexdigest()[:8])
PY
)"
[ "$NEW" = "$ID" ] && pass "BUILD_ID $ID matches current overlay+patches+lock" || fail "BUILD_ID $ID != recomputed $NEW (stale artifact)"

# Linked part of the map = after "Linker script and memory map"; symbols table from the ELF
# (the Cross Reference Table lists symbols *defined* by linked objects that --gc-sections later drops, so it is excluded)
LINKED="$(sed -n '/^Linker script and memory map/,$p' "$MAP" | sed '/^Cross Reference Table/,$d')"
NM="$(arm-none-eabi-nm "$ELF")"
# With -flto the static-call-site functions below may be inlined into their callers and lose their symbol:
# accept absence only if the overlay still defines them (the entry points rxdiagCliRun etc. must still link).
for s in targetConfiguration targetPreInit rxdiagRun; do
  if echo "$NM" | grep -qw "$s"; then pass "elf contains $s"
  elif grep -rqE "^[a-zA-Z_ ]+[ *]$s\(" "$FW/overlay/src/main"; then pass "$s defined in overlay, inlined by LTO (no symbol)"
  else fail "missing $s"; fi
done
for s in targetValidateConfiguration rxdiagCliRun CDC_Send_DATA_NB motorWriteNull; do
  if echo "$LINKED" | grep -qw "$s" && echo "$NM" | grep -qw "$s"; then pass "map+elf contain $s"; else fail "missing $s"; fi
done
FORB='cc2500WriteFifo|cc2500SetPower|cc2500TxEnable|cc2500ReadReg|frSky|FrSky|sfhss|Sfhss|redpine|Redpine|esc4wayInit|escEnablePassthrough|cliEscPassthrough|motorPwmDevInit|dshotPwmDevInit|dshotBitbangDevInit'
for what in LINKED NM; do
  H="$(echo "${!what}" | grep -E "$FORB" | head -5)"
  [ -z "$H" ] && pass "no forbidden symbol in $what" || { fail "forbidden symbol in $what:"; echo "$H"; }
done
# any cc2500 function at all, and any protocol/4way/escserial leftovers
H="$(echo "$NM" | grep -iE ' [TtWw] .*(cc2500|4way|escserial|esc_serial)' | head -5)"
[ -z "$H" ] && pass "no cc2500/4way/escserial text symbols in ELF" || { fail "leftover symbols"; echo "$H"; }

# strings
strings "$BIN" | grep -q "MATEKF411RX-RXDIAG" && pass "bin has MATEKF411RX-RXDIAG" || fail "bin lacks product string"
strings "$BIN" | grep -q "$ID" && pass "bin has BUILD_ID $ID" || fail "bin lacks BUILD_ID"
strings "$BIN" | grep -q "M41R" && pass "bin has board id M41R" || fail "bin lacks M41R"

# fits FLASH1 (length taken from the linker's own Memory Configuration in the map)
LIM="$(awk '$1=="FLASH1"{print $3; exit}' "$MAP")"; LIM=$((LIM)); FLASH_K=$((LIM/1024))
SZ="$(arm-none-eabi-size "$ELF" | tail -1)"
TEXT="$(echo "$SZ" | awk '{print $1}')"; DATA="$(echo "$SZ" | awk '{print $2}')"
USED=$((TEXT + DATA)); if [ "$LIM" -gt 0 ] && [ "$USED" -le "$LIM" ]; then pass "text+data $USED B <= FLASH1 ${FLASH_K}K ($LIM B); bin $(stat -f %z "$BIN") B"; else fail "size $USED > $LIM"; fi
echo "$SZ" > "$OUT/size-checked.txt"

# core compiles strictly with the pinned cross compiler
CORE="$FW/overlay/src/main/rx/rxdiag_core.c"
if arm-none-eabi-gcc -std=c99 -Wall -Wextra -Werror -mcpu=cortex-m4 -mthumb -Os -c "$CORE" -o /tmp/rxdiag_core_check.o 2>/tmp/rxdiag_core_check.err; then pass "core compiles -std=c99 -Wall -Wextra -Werror (arm-none-eabi-gcc $(arm-none-eabi-gcc -dumpversion))"; else fail "core strict compile"; cat /tmp/rxdiag_core_check.err | head; fi
# core pulls in no libc printf family / no Betaflight symbols
if arm-none-eabi-nm -u /tmp/rxdiag_core_check.o | grep -Eq 'printf|malloc|calloc'; then fail "core references printf/malloc"; else pass "core has no printf/malloc references"; fi

BIN_SHA="$(shasum -a 256 "$BIN" | awk '{print $1}')"
echo "INFO artifact $BIN sha256 $BIN_SHA"
[ $FAILS -eq 0 ] && { echo "check_build: ALL PASS"; exit 0; } || { echo "check_build: $FAILS FAIL"; exit 1; }
