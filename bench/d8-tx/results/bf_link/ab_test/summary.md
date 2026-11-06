# ab_test summary (live-sticks firmware d8tone.bin sha256 fdb6c322…aeec, flashed app-only, PING ok, STAT keyed=0)

Source-off (`rxdiag hop 2 55 5000 2403937`): 3 crc-fail noise P records (len 3/7/10), no LOCK/valid packet -> proceed.
STAT keyed=0 after every run. No ERR. All K lines in `*_esp.txt`.

| run | FOFS / base | slots | valid | rate | longest loss | silent tail | ESP K |
|---|---|---|---|---|---|---|---|
| A1 | 0 / 2404000 | 556 | 542 | 97.5% | 1 | no | done, late_max 96 us |
| B1 | -63000 / 2403937 | 556 | 542 | 97.5% | 2 | no | done, 17 us |
| A2 | 0 / 2404000 | 556 | 538 | 96.8% | 1 | no | done, 17 us |
| B2 | -63000 / 2403937 | 556 | 537 | 96.6% | 2 | no | done, 17 us |
| cont2 (HOP 0 127 300, S 8 s, U) | -63000 / 2403937 | 891 | 869 | 97.5% | 2 | no | why=stop, late_max 262 us |
| timeout2 (S 2 s, then silent) | -63000 / 2403937 | 257 | 251 | 97.7% | 1 | no | why=timeout ~0.31 s after last S |

A vs B: no meaningful difference (97.1% vs 97.0% mean). Earlier 85-92% and the 47-slot tail did not reproduce.
Counter continuous, no discontinuities, tx id 42B2, no channel mismatches.
Decoded sticks in cont2/timeout2: single frame (1500,2250,2250,2250,1500,1500,1500,1500) raw = S 1000 1500 1500 1500 1000... x1.5 -> matches.
U stopped cleanly (K why=stop, STAT keyed=0).

Harness notes: first `cont`/`timeout` runs (files `cont*`, `timeout*` without 2) had a harness bug: first S sent 0.3 s after
HOP 0, so ESP hit its 300 ms timeout before any S (why=timeout, slots=34, keyed=0 afterwards). That shows the timeout itself works.
They are not valid continuous-mode results. Rerun as cont2/timeout2 (approved: 8 keyed runs total).
Measured S rate in reruns: ~74 Hz (591 S/8 s, 149/2 s), below the 111 Hz slot rate (host loop limited by serial polling); the ESP held every slot keyed regardless.
