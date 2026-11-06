# Retune gate (wave 2 step 2), RETUNE <khz> then TONE 0 150000 127 (150 ms), ESP at 921600 baud
Receiver: `rxdiag freq <khz> 100 102 203 66 1200` (fw f39fac05), tone keyed ~0.6 s into each 1.2 s capture.
Raw data: raw.txt (script run_gate.py); per-window table: summary_table.txt. RSSI is raw signed counts (dBm ≈ raw/2 − 74).

| khz | baseline max RSSI | keyed max RSSI (3 tones) | FREQEST at keyed peak (kHz, 3 tones) | verdict |
|---|---|---|---|---|
| 2412000 | -41 (CS never) | 33, 35, 33 | -3.2, +11.1, -4.8 | PASS |
| 2404000 | -6 (CS never) | 31, 35, 31 | -12.7, +4.8, -12.7 | PASS |
| 2441000 | -2 (CS in all windows, ncs<=144/window: steady in-band interferer, not packet-like) | 29, 21, 29 | +6.2, -12.5, +1.6 | PASS (smaller rise ~23-31 counts) |
| 2478000 | -50 (CS never) | 22, 21, 21 | -11.2, -12.7, -12.7 | PASS |

Each tone shows 2 CS windows (≈150 ms), all |offset| <= 13 kHz. Final: RETUNE 2412000 OK, STAT keyed=0.
No packet-like baseline activity; the 2441 baseline carrier-sense is low-level constant (ncs≤144 vs ~1800 keyed), consistent with ambient noise.
