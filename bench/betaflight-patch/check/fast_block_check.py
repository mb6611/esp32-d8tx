#!/usr/bin/env python3
"""Cross-check the FAST block bit layout: compile the C packer extracted from patches/0003 (FASTPACK markers) and compare
with an independent Python pack/unpack per .ru/plans/fast-telemetry.md. No hardware. Prints a sample block."""
import os, random, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "patches", "0003-frsky-d-fast-block.patch")).read()
m = re.search(r"^\+// FASTPACK-BEGIN.*?\n(.*?)^\+// FASTPACK-END", src, re.S | re.M)
code = "".join(l[1:] + "\n" for l in m.group(1).splitlines())
harness = '#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n' + code + '''
int main(void){ int32_t a[7]; while (scanf("%d %d %d %d %d %d %d",a,a+1,a+2,a+3,a+4,a+5,a+6)==7){ uint8_t o[10];
 frSkyDPackFast(o,a[0],a[1],a[2],a[3],a[4],a[5],a[6]); for(int i=0;i<10;i++)printf("%02x",o[i]); printf("\\n"); } return 0; }'''
W = [12, 12, 12, 14, 14, 14, 2]
def clamp(v, lo, hi): return max(lo, min(hi, v))
def pack(r, p, y, gx, gy, gz, seq):
    vals = [clamp(r,-2048,2047), clamp(p,-2048,2047), clamp(y,0,3599), clamp(gx,-8192,8191), clamp(gy,-8192,8191), clamp(gz,-8192,8191), seq & 3]
    v = sh = 0
    for x, w in zip(vals, W): v |= (x & ((1 << w) - 1)) << sh; sh += w
    return v.to_bytes(10, "little")
def unpack(b):
    v = int.from_bytes(b, "little"); out = []; sh = 0
    for i, w in enumerate(W):
        x = (v >> sh) & ((1 << w) - 1); sh += w
        if i in (0, 1, 3, 4, 5) and x >= 1 << (w - 1): x -= 1 << w
        out.append(x)
    r, p, y, gx, gy, gz, seq = out
    return dict(roll_deg=r/10, pitch_deg=p/10, yaw_deg=y/10, gyro_dps=[gx/4, gy/4, gz/4], seq=seq)
random.seed(1)
cases = [(123,-456,2700,-40,2000,-8192,2), (0,0,0,0,0,0,0), (1800,900,3599,8191,-8192,1,3), (-1800,-900,0,-1,-1,-1,1), (5000,-5000,4000,99999,-99999,0,7)]
cases += [(random.randint(-2500,2500), random.randint(-2500,2500), random.randint(-100,3700), *[random.randint(-9000,9000) for _ in range(3)], random.randint(0,3)) for _ in range(2000)]
with tempfile.TemporaryDirectory() as d:
    open(d + "/t.c", "w").write(harness)
    subprocess.check_call(["cc", "-O1", "-Wall", "-o", d + "/t", d + "/t.c"])
    res = subprocess.run([d + "/t"], input="\n".join(" ".join(map(str, c)) for c in cases), capture_output=True, text=True, check=True).stdout.split()
bad = 0
for c, h in zip(cases, res):
    if h != pack(*c).hex(): bad += 1; print("MISMATCH", c, h, pack(*c).hex())
assert len(res) == len(cases)
print("sample:", cases[0], "->", res[0], unpack(bytes.fromhex(res[0])))
print("cases %d, mismatches %d" % (len(cases), bad)); sys.exit(1 if bad else 0)
