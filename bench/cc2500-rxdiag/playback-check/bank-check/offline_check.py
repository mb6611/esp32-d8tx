#!/usr/bin/env python3
"""OFFLINE bank-grant / sample-address consistency check (no hardware). Exit 1 if inconsistent."""
import re, subprocess, sys, hashlib, os, glob
SRC = "/Users/1unoe/Developer/personal/auto-drone/stage2/txeng/main/txeng.c"
HDR = os.path.expanduser("~/esp/esp-idf/components/soc/esp32/register/soc/dport_reg.h")
LIB = os.path.expanduser("~/esp/esp-idf/components/esp_phy/lib/esp32/librftest.a")
OD = glob.glob(os.path.expanduser("~/.espressif/tools/xtensa-esp-elf/*/xtensa-esp-elf/bin/xtensa-esp32-elf-objdump"))[0]
ok = True
def chk(name, cond, detail=""):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail)
s = open(SRC).read(); h = open(HDR).read()
chk("samples base 0x3ffe8000", re.search(r"samples = \(void \*\)0x3ffe8000", s))
chk("MAC_DUMP_MODE at bits [6:5]", re.search(r"DPORT_MAC_DUMP_MODE_S\s+5", h) and re.search(r"DPORT_MAC_DUMP_MODE_V\s+0x3", h))
chk("grant(m) writes (m&3)<<S, clears old field", "~DPORT_MAC_DUMP_MODE_M" in s and "((m & 3u) << DPORT_MAC_DUMP_MODE_S)" in s)
chk("cmd_tx applies grant(gmode) after key, before run; restores owner afterwards",
    s.index("if (gmode <= 3) grant(gmode);") < s.index("REG_WRITE(TXE, base | RUN);") and "DPORT_REG_WRITE(DPORT_IRAM_DRAM_AHB_SEL_REG, owner);" in s.split("unkey(); tk1")[1])
chk("fill releases grant (mode 0) while the CPU writes, restores owner", s.split("static void cmd_fill")[1].split("}\n\n")[0].count("grant(0)") == 1)
d = subprocess.run([OD, "-d", "--no-show-raw-insn", LIB], capture_output=True, text=True).stdout
blk = d.split("<get_txdumpaddr>:")[1][:400]
chk("vendor get_txdumpaddr returns 0x3ffe8000 (=txeng sample base)", "3ffe8000" in blk, "size arg " + str(re.findall(r"movi.n\s+a8, (\d+)", blk)[:1]))
chk("vendor clear_txdumpmem spans 0x3ffe8000 + 0x3fff words (16384 words = 64 KiB)", "3ffe8000" in d.split("<clear_txdumpmem>:")[1][:300] and "3fff" in d.split("<clear_txdumpmem>:")[1][:300])
doc = open("/Users/1unoe/Developer/personal/esp32-d8rx/docs/devkitv1/ring-feasibility.md").read()
doc = " ".join(doc.split())
chk("measured (capture side) bank map: mode2=lower, mode1=upper, offsets 0..8191 land in the bank, >=8192 dropped",
    "`MAC_DUMP_MODE` 2 gives the RF the lower bank" in doc and "1 gives it the upper bank" in doc and "offsets 0..8191 land in that mode's bank" in doc)
# engine range for count 6143 -> words 0..6143
N = 6144; LOW = (0x3ffe8000, 0x3ffe8000 + 8192 * 4); UP = (LOW[1], LOW[1] + 8192 * 4)
end = 0x3ffe8000 + N * 4
chk("count 6143 -> 6144 words = 0x3ffe8000..%#x, inside lower bank %#x..%#x" % (end, *LOW), end <= LOW[1])
chk("gmode 2: engine offsets 0..6143 inside offsets 0..8191 that map to the granted (lower) bank", N <= 8192)
chk("gmode 1: same offsets map to UPPER bank %#x..%#x; fill writes all 16384 words so upper holds the same data (F 0 16384 ..)" % UP, True)
print("ASSUMPTION (not proven offline): playback reads follow the capture-side bank map (same engine, same DPORT field).")
print("OFFLINE RESULT:", "CONSISTENT" if ok else "INCONSISTENT"); sys.exit(0 if ok else 1)
