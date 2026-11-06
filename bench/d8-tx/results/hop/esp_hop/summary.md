# ESP32 hopping (wave 2 step 4), receiver `rxdiag hop 2 55 <ms> 2404000` (fw f39fac05), ESP `HOP <n> 127`, STICKS 1500
Source-off (5 s, ESP idle): no LOCK, no 0x11 packet (1 CRC-bad 12-byte noise P). PING d8tone, STAT keyed=0 before/after every run.
| | E8 control (20 s) | Run A (556 slots) | Run B (940 slots) |
|---|---|---|---|
| slots | 2204 | 556 | 940 |
| CRC-valid | 2133 (96.8%) | 543 (97.7%) | 921 (98.0%) |
| longest loss run | 1 | 1 | 2 (slot 926) |
| counter discontinuities | 0 | 0 | 0 |
| stick frames / decode | 1 | 1, raw 2250 = 1500 us | 1, raw 2250 = 1500 us |
| chan mismatches / id | 0 / 42B2 | 0 / 42B2 | 0 / 42B2 |
| RESYNC | - | 1 (slot 656, after ESP stopped at 556) | 1 (slot 1040, after ESP stopped at 940) |
ESP: A `K,hop,slots=556,late_max_us=80,retune_max_us=363`; B `K,hop,slots=940,late_max_us=81,retune_max_us=389`. No ERR, keyed=0 after each.
Per-channel: all 47 channels valid; losses spread, max 1-2 per channel (no weak channel like E8's ch133/25). Files: runA/B.txt, *_esp.txt, *_stats.txt, *_hop_map.png, driver.py.
