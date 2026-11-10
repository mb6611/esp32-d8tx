# fine-step check (7 keyings, 150 ms, pwr 127, bw102 agc 203/66, scan3.py = scan2.py with fine/ dir, envelope max_abs_offset 4). All OK, no miss, no reboot, STAT keyed=0 each.
Fine-bits readback = K line field 15 (hex): f=+1:1, +2:2, +4:0, -1:3, -2:2, -4:0 (= f&3; matches ROM split). Gain-edge: ncs ~1950-1980 (f=0-like) in all.
| setting | predicted kHz | fc | hit | rssi | ncs | fe stable | measured |
|---|---|---|---|---|---|---|---|
| +1 | +39 | 2412039 | yes | 15 | 1971 | no (-8..2) | fe unusable; within ~±50 of 2412039 |
| -1 | -39 | 2411961 | yes | 19 | 1965 | yes (-2) | 2411957.8 = -42.2 |
| +2 | +78 | 2412078 | yes | 18 | 1973 | no (-4..3) | within ~±50 of fc |
| -2 | -78 | 2411922 | yes | 14 | 1981 | yes (-3) | 2411917.2 = -82.8 |
| +4 | +156 | 2412156 | yes | 20 | 1956 | no (-1..6) | within ~±50 of fc |
| -4 | -156 | 2411844 | yes | 21 | 1953 | yes (+7) | 2411855.1 = -144.9 |
Control fc=2412000 f=+1: keyed ncs 1765, rssi_max 2 (windows -1,2,-6), base ncs 68 -> weak (rssi 2 vs 15-20), consistent with tone off-center (~+39) at filter edge.
Caveat: fe_mean_hz is coarse (FREQEST units ~1.5 kHz/count, sign/scale per rxdiag) and unstable for + settings; hit window ±~50 kHz, so ±1/±2 only distinguish from f=0 by rssi roll-off. No misses so no probing.
