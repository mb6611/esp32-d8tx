# U4 scan (bw 102, agc 203/66, power 127, 150 ms tones, `rxdiag freq <fc> 100 102 203 66 1200`)
Script scan.py (adapted from rerun3.py; fc list + tone from argv). Only fc 2411500..2412500 step 50 kHz. All commands OK, STAT keyed=0 after each, no reboot/overrun.
(Aborted first attempt: mistyped fc 2362000.. and no keying happened; an envelope-budget abort after 12 cmds, fixed by scaling budget.) Total keyings: 40 scan (+16: 20, -16: 20) + 6 confirm + 3 center.
Columns: peak-ncs window among keyed windows 4-6; rssi_max over those; base = max ncs in windows 0-3 (pre-key noise); stable = fe_min==fe_max in peak window.
| fc kHz | tone | peak ncs | base ncs | rssi_max | fe stable | fe_mean_hz |
|---|---|---|---|---|---|---|
| 2411500 | +16 r1 | 238 | 358 | 10 | N | -1473 |
| 2411550 | +16 r1 | 168 | 165 | 9 | N | -340 |
| 2411600 | +16 r1 | 180 | 247 | 9 | N | -70 |
| 2411650 | +16 r1 | 375 | 166 | 11 | N | -926 |
| 2411700 | +16 r1 | 171 | 226 | 8 | N | 928 |
| 2411750 | +16 r1 | 7 | 83 | -5 | N | -2493 |
| 2411800 | +16 r1 | 0 | 0 | -13 | Y | 0 |
| 2411850 | +16 r1 | 0 | 0 | -13 | Y | 0 |
| 2411900 | +16 r1 | 0 | 0 | -17 | Y | 0 |
| 2411950 | +16 r1 | 0 | 0 | -16 | Y | 0 |
| 2412050 | +16 r1 | 1915 | 0 | 1 | N | -10560 |
| 2412100 | +16 r1 | 0 | 0 | -11 | Y | 0 |
| 2412150 | +16 r1 | 16 | 18 | -5 | N | -5157 |
| 2412200 | +16 r1 | 56 | 51 | -5 | N | 1048 |
| 2412250 | +16 r1 | 98 | 94 | -2 | N | -2445 |
| 2412300 | +16 r1 | 430 | 508 | 1 | N | -727 |
| 2412350 | +16 r1 | 216 | 131 | 2 | N | -2982 |
| 2412400 | +16 r1 | 135 | 198 | 4 | N | -1140 |
| 2412450 | +16 r1 | 190 | 168 | 4 | N | 860 |
| 2412500 | +16 r1 | 244 | 456 | 7 | N | -1398 |
| 2411500 | -16 r1 | 600 | 547 | 5 | N | -782 |
| 2411550 | -16 r1 | 172 | 205 | 3 | N | -784 |
| 2411600 | -16 r1 | 393 | 282 | 3 | N | -1122 |
| 2411650 | -16 r1 | 1678 | 411 | 2 | N | -10924 |
| 2411700 | -16 r1 | 0 | 0 | -20 | Y | 0 |
| 2411750 | -16 r1 | 0 | 0 | -26 | Y | 0 |
| 2411800 | -16 r1 | 0 | 0 | -24 | Y | 0 |
| 2411850 | -16 r1 | 0 | 0 | -21 | Y | 0 |
| 2411900 | -16 r1 | 0 | 0 | -28 | Y | 0 |
| 2411950 | -16 r1 | 0 | 0 | -29 | Y | 0 |
| 2412050 | -16 r1 | 1957 | 0 | 1 | Y | 4760 |
| 2412100 | -16 r1 | 0 | 0 | -9 | Y | 0 |
| 2412150 | -16 r1 | 0 | 0 | -14 | Y | 0 |
| 2412200 | -16 r1 | 23 | 0 | 22 | N | -896 |
| 2412250 | -16 r1 | 0 | 0 | -12 | Y | 0 |
| 2412300 | -16 r1 | 0 | 0 | -6 | Y | 0 |
| 2412350 | -16 r1 | 113 | 92 | -3 | N | -1586 |
| 2412400 | -16 r1 | 24 | 39 | -4 | N | 2115 |
| 2412450 | -16 r1 | 90 | 71 | -1 | N | 1040 |
| 2412500 | -16 r1 | 50 | 20 | -6 | N | -4030 |
| 2412050 | +16 r1 | 1907 | 0 | 0 | N | -256 |
| 2412050 | +16 r2 | 1912 | 59 | -1 | N | 10330 |
| 2412050 | -16 r1 | 1858 | 1004 | 6 | N | -10794 |
| 2412050 | -16 r2 | 1879 | 172 | 5 | N | -6553 |
| 2412200 | -16 r1 | 376 | 159 | 4 | N | -2726 |
| 2412200 | -16 r2 | 445 | 339 | 14 | N | -2417 |
| 2412000 | +0 r1 | 1944 | 222 | 21 | Y | 11108 |
| 2412000 | +0 r2 | 1953 | 62 | 16 | N | -8950 |
| 2412000 | +0 r3 | 1937 | 31 | 21 | Y | 7934 |

## Result: NOT located
- No fc in +-500 kHz shows the f=0 signature (rssi +13..+21 and ncs ~1950) for +16 or -16. Best is fc 2412050: ncs ~1900 with base ~0 for both tones (so a carrier is in-band there), but rssi only -2..+6, and FE unstable on confirm (+16: -256, +10330; -16: -10794, -6553; one unconfirmed stable hit 4760). 2412200/-16 had rssi +22 once with ncs 23, not reproduced (+14 / ncs 445 on confirm, FE rail-to-rail).
- Many fc (2411800..2411950, 2412100, 2412150 etc.) read ncs 0, rssi -13..-34, FE 0: channel quiet, tone not visible. Several others (2411500-2411700, 2412300+) have base ncs 100-1000 already pre-key = ambient interference, so ncs there is meaningless.
- Interpretation: a tone seen only near 2412050 (~+50 kHz, weakly) at both signs is not consistent with a simple +-N kHz shift of a constant carrier; no kHz-per-step can be derived. rssi at 2412050 is ~15-20 dB below the f=0 level at 2412000, the +-16 tone may just sit on the filter skirt, or the +-16 output is a spread/non-CW signal.
## Center tone (fc 2412000, TONE 0, 3 more keyings)
fe_mean_hz: +11108 (stable, rail +7), -8950 (-7..-4), +7934 (stable, 5). With rerun3 (-9.5k, +11.1k, -12.7k) that is 6 keyings with FE random in sign and magnitude +-8..+11k; ncs ~1940-1950 and rssi 15-21 consistently. So FE at the center tone is NOT repeatable between keyings (carrier freq of the ESP tone or CC2500 FE estimate varies by >20 kHz per keying) and FE-based frequency measurement is not usable at this setup.
