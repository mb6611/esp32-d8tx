# Bank-grant check: all-zero vs constant I=200,Q=0 playback, 2412 MHz (2026-11-06)
**Result: NO sample-dependent RF detected with lower bank alone (gmode 2): valid, control passed, NO-DIFF. Upper bank (gmode 1): NO-CONTROL (tone 6/8 < 7/8 gate), dc vs zero no difference but not interpretable under prereg. Sample dependence neither shown nor excluded.**
Limits kept: ch1 2412, K 0, pwr 127/0, count 6143, tmo 100, abort>400 us, slots>=0.35 s; RX `rxdiag events 2412000 100 203 203 66 1`. No abort, no hang, max keyed_us 368 (first keyed slot after boot), others 194-206 (g2 first 321).
- Offline (`offline_check.py/.txt`, CONSISTENT): sample base 0x3ffe8000 = vendor `get_txdumpaddr` (returns 0x3ffe8000, 12) = txeng `samples`; grant() writes DPORT MAC_DUMP_MODE bits[6:5]; count 6143 -> words 0..6143 = 0x3ffe8000..0x3ffee000, inside lower bank; mode 2 = lower, mode 1 = upper (measured on capture side, ring-feasibility.md). ASSUMED not proven: playback reads follow the same map. Fill writes all 16384 words (both banks hold the data).
- Prereg `prereg.py` (sha in prereg.sha256, verified before each session, saved 2026-11-06T03:29Z before keying). dc vs zero two-sided MWU/Fisher alpha .025 + |median diff|>=3.
- Slots n=8/cond (tone, dc, zero, unkey, idle; seeds 2001/2002): hits (Clopper-Pearson 95%), peak raw, per-slot values in `g2/result.json`, `g1/result.json`, `*_result.txt`.

| gmode | cond | hits | peak median (raw) | peaks |
|---|---|---|---|---|
| 2 (lower) | tone | 8/8 [.63,1] | 22 | 16..25 |
| 2 | dc | 8/8 [.63,1] | -1 | -8..2 |
| 2 | zero | 8/8 [.63,1] | -1 | -5..3 |
| 2 | unkey / idle | 0/8, 0/8 [0,.37] | | |
g2: control PASS, not saturated, MWU two-sided p=0.851, median diff 0, Fisher p=1 -> NO-DIFF.

| 1 (upper) | tone | 6/8 [.35,.97] | 20 | 17..25 (2 misses) |
|---|---|---|---|---|
| 1 | dc | 7/8 [.47,1.0] | -5 | -12..-3 (+1 miss) |
| 1 | zero | 7/8 [.47,1.0] | -7 | -9..-2 (+1 miss) |
| 1 | unkey / idle | 0/8, 0/8 | | |
g1: control FAIL (tone 6/8 < 7), outcome NO-CONTROL; MWU p=0.873, median diff +2, Fisher p=1 (informational only).
Interpretation: keyed energy (tone, and keyed zero at LO) is seen; dc vs zero indistinguishable in both banks (hit counts and peaks overlap, differences << CI). Tone-bit-cleared dc and zero are keyed identically, so the null is about samples only. Caveats as before: DC may be masked by LO leakage/removal, 10-bit I/Q format and sign unverified, 77 us burst, one RX offset, uncalibrated RSSI, n=8. No in-slice non-DC positive control exists.
## Restore
ESP32: pre-image `esp_preimage.bin` (sha esp_preimage.sha256) written back and verified (`esp_restore_verify.log` digest matched); `esp32sdr info` identical before/after. Tinyhawk: diag 4cd0deab flashed by DFU (`diag_info.txt`), stock 4.2.11 restored by DFU (`dfu_restore_stock.txt`), `diff all` replayed (`restore_replay.log`, 0 ERROR lines), final capture matches preflash apart from uptime/temp/voltage lines. Ports free (lsof empty).
