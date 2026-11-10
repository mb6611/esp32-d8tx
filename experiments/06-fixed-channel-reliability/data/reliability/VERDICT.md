# U3.4 verdict — D8 fixed-channel ESP32 TX reliability (PRIVATE)

Offline write-up from the existing raw logs only; no hardware, ports, RF, flash or commit were used.
Fixed channel (2412000 kHz, ESP center; 2421032 kHz for E8), no hopping.

## Setup
- Receiver: corrected image fw `c5cc593b`, bf `948ba63`, quiet_us=2000. `.bin` sha256
  `e71d794c4a697ee99e03f9fa7c13ba7239d68fafd484f3642cfb4b3f73f6937c` (bench/cc2500-rxdiag/firmware/out/c5cc593b/SHA256SUMS; checksums OK in `stm_checksum_verify.txt`).
- Initial E8 positive control `control_e8_2421032.txt`: 46 CRC-valid, all 18 B 1142B200 (recount: 46).
- Final E8 control `control_e8_post10_2421032.txt`: 41 CRC-valid (recount: 41), PASS.
- Source-off 5 s control at the ESP frequency before each group: 0 CRC-valid, 0 expected-ID lines. Batch 1b reused the earlier `source_off_batch1_2412000.txt` after the refused 0-RF envelope (~380 s earlier); batches 2–10 each took a fresh capture immediately before sending.
- 10 physical groups, 10 PKT each = 100 PKT; every ESP `attempts.json` for 1b..10 shows 10/10 command ok, on_us=6700.
  Group "batch1" was refused by the envelope (`offset exceeds envelope 0`, zero RF; STM log has noise only); not counted. Batch 1b is the re-run.
- Battery absent. E8 owner-controlled: ON for controls, OFF during ESP runs. Post-run ESP STAT `keyed=0` (e.g. `post_batch10_esp.txt`).

## Per-batch four-class results (valid / crc_invalid / malformed / unobserved)
| batch | valid | unobserved | note |
|---|---|---|---|
| 1b | 9 | 1 | stm log recount: 9 matching CRC-valid; no report file (counted from batch1b_stm.txt) |
| 2 | 0 strict | 10 strict | 8 raw matching CRC-valid (seq 1-5,7,8,10), each ambiguous between two attempt windows; clock uncertainty 0.54 s; per-attempt mapping NOT established |
| 3 | 9 | 1 | |
| 4 | 10 | 0 | |
| 5 | 10 | 0 | |
| 6 | 8 | 2 | |
| 7 | 10 | 0 | |
| 8 | 10 | 0 | |
| 9 | 9 | 1 | |
| 10 | 10 | 0 | |

crc_invalid=0, malformed=0 in every report.

## Pooled
- 85 attributed CRC-valid; 5 unobserved in attributable runs (1b,3,6x2,9 -> 1+1+2+1); 10 ambiguous per-attempt (batch 2).
- 85 + 8 = **93 raw matching CRC-valid receptions** total. This is NOT 93 individually proven successes: 8 are batch-2 receptions that cannot be tied to specific attempts.
- 0 matching real CRC-invalid / EPART / receiver E errors. Non-matching noise (other-length CRC-fail lines) is separate and not counted.

## Deviations / limits
- Batch1 refused-envelope retry (offset envelope 0 -> new envelope as 1b) and ad-hoc process; initial runs (1b, 2) used hand scripts (`run_batch1*.py`, `batch2_run.py`) with a coarse host/STM clock anchor; later batches used `batch3_driver.py` with a tighter anchor (~0.03–0.04 s). Batch 2 was classified conservatively and a post-hoc 0.12 s variant (`batch2_report_posthoc_post0.12.txt`) still gave 0/10.
- Batch 1b reused the prior source-off check and lacks fresh pre/post idle logs, a start-write anchor and a per-batch hashes file; batch 2 lacks a start-write anchor and a per-batch hashes file, and its post-idle check was recorded later. Batches 3–10 have `batchN_hashes.txt` (all re-verified OK).
- Single receiver/antenna placement, one channel, ~0.5 s spacing, 100 PKT.

## Conclusion
Fixed-channel measurement shows the ESP32 PKT path is received CRC-valid most of the time on the bench (>=85/90 attributable; 93 raw receptions over 100 commands) with occasional unobserved attempts. It does **not** establish an ESP-only drop percentage (receiver loss, startup timing, interference not separated), an RF cause, hopping behaviour, or any statistical guarantee.

## Recommendation
Next, a non-hopping diagnostic of startup timing (e.g. batch3 attempt 0 unobserved; batch6 attempts 5,6 mid-run), interference, and receiver-side loss (e.g. E8-vs-ESP receiver loss rate) with a better clock anchor. **No RF request now**; needs a fresh owner decision.

## Offline checks (repo root)
```
# From the private TX repository root:
for b in 3 4 5 6 7 8 9 10; do shasum -a 256 -c bench/d8-tx/results/packet/reliability/batch${b}_hashes.txt; done
cd bench/d8-tx/results/packet/reliability
shasum -a 256 -c VERDICT.sha256            # anchors for stm/control/envelope logs
grep -c ',1$' control_e8_2421032.txt control_e8_post10_2421032.txt    # 46, 41
for f in source_off_batch*_2412000.txt; do grep -c ',1$' $f; done     # all 0
grep -h '^attempts' batch*_report.txt                                  # batches 2-10 (1b has none)
grep -c ',18,1142B2000001CACA' batch1b_stm.txt                         # 9 ; batch2_stm.txt -> 8
```
## Hash anchors
control_e8 74c92a9f2a93d4262afb639c7906a06bbea64c19e1d24574ccb152eb9a6829c8; control_e8_post10 5ba71e1338b2fa5d2772c45b2a20d153bd0f750bdd84acf3cb1ff53d08dd431d; per-batch stm hashes in VERDICT.sha256.
