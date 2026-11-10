# Patched Betaflight hub fields: bench result 2026-11-08 (drone on USB, no battery, ~0 V)

## Flash
- First image f9420b39 (sha f0f30b99...fca22) flashed via CLI `bl` + dfu-util (needed 2 tries: first one died in ERASE_PAGE get_status, retry OK).
  Result: **NO_GYRO** in arming flags. Cause: the bare MATEKF411RX target only builds the MPU6000 driver; this Tinyhawk has an
  ICM20689 (stock cloud build includes it). Fix = `patches/0002-matekf411rx-icm20689.patch` (target.h + target.mk, adds driver).
- Rebuilt: image **a7c24987**, 431488 bytes, sha256 c24cfa44bd8982d0112b71f289c7f11e1c265706df52514e5a468257efef7dcc
  (`out/a7c24987/`), flashed OK (dfu-util 1st try). `GYRO=ICM20689, ACC=ICM20689`, gyro rate 8000, no NO_GYRO.
  The bare target has built-in target defaults (resources, rx_spi_bus 3, cc2500 detect OFF ...) so `diff all` after is shorter than before.
- Config replay: `replay_input.txt` (= diff_all_before minus echo lines) pasted, `resource RX_SPI_LED 1 NONE`, `save`.
  `set mag_hardware/baro_hardware` are unknown names in this build (harmless, no such sensors).
- diff_all_before.txt (stock, no custom defaults) vs diff_all_after.txt: every `set` line of before is either present after or is now
  a built-in default (rx_spi_bus, led inversion, dshot_burst, current/battery meter, ibata_scale, beeper, hse, max7456 bus, gyro_1_* ...).
  Invariants verified: frsky_spi_tx_id 66,178; offset -32; hop table identical; Enabled features TELEMETRY OSD AIRMODE RX_SPI ANTI_GRAVITY
  DYNAMIC_FILTER (LED_STRIP off); RX_SPI_LED NONE. **`resource LED 1 C13` is still listed** (target default; `resource LED 1 NONE` was
  accepted but did not stick in the listing; it was not in the stock config either, the stock listing simply had no LED 1 line). LED_STRIP feature off.
- Pitfall: while a CLI replay was done, leaving CLI with `exit` reboots WITHOUT saving; an unsaved paste is lost (happened twice).
  Always `save` (reboots itself) and do not `exit`. Do not send '#' when already in CLI.
- ESP32 firmware pitfall: after a host crash/close the board can stay in a capture stream; reset via RTS, then wait >=4 s before the next
  tlm_listen (closing the port resets the chip again, boot takes ~2 s) or PING gets no reply.

## Radio (ESP32 link, --fofs -75000 --stream --ack --every 48, 90 s; run `link_20261108-103352/`)
- 207/208 triggers answered (99.5%). hub_bytes 1735, hub_frames 421.
- Decoded (mean over 52 samples): **ACC X -28.1 mg, Y -46.7 mg, Z +1004.5 mg** (range Z 1003..1006), i.e. level, 1 g. STATUS value 2 (ANGLE, bit1) mostly, 18 at
  start; ARMING_DISABLE 0 (4 = RXLOSS early). Gyro dps ~ +-0.6 (raw 0.1 dps units: -3..6). Attitude roll -2.7 deg, pitch +1.6 deg (raw -27/16 deci-deg), yaw 359.3.
- Stock fields still arriving: TEMP1/RPM/VOLT/VOLTAGE_AMP/CURRENT/FUEL all 0 (no battery), HOUR_MINUTE/SECOND. RSSI ~ -55 dBm, A1/A2 0 (USB).
- Frame counts over 90 s (trigger every 48 slots = 2.3 replies/s, <=10 hub bytes each): STATUS, ARMING_DISABLE, ACC x3: 52 (0.58 Hz);
  GYRO x3: 26 (0.29 Hz); ATT x3: 13 (0.14 Hz); stock slow fields (VOLT etc.): 6 (0.067 Hz). Ratio 4:2:1 holds = plan's 8:4:2 relative rate;
  absolute rates are capped by our one-reply-per-48-slots trigger (~19 B/s measured), not by the drone. Stock-only earlier run (SUMMARY.md, 60 s):
  ACC 51 frames per 139 triggers (0.37/trigger) vs now 52 per 208 (0.25/trigger): the extra fields share the same reply bandwidth, so each
  existing field updates ~30% less often per trigger (ratio-wise, no IDs lost; all stock IDs still seen). The plan's 8/4/2 Hz needs ~10+ triggers/s
  (`--every ~10`); NOT measured: the ESP32 hung before the faster run (see pitfall) and the lock was overdue.
## Arming test (armtest.py, armtest_log.csv, armtest_events.json; voltage 0 before: vbat_cv 1)
D8Link allow_arm, throttle low, ch7 high at t=14.02 s, low at t=24.02 s (script clock):
- arm: MSP armed flag 0->1 at 14.169 s (+0.15 s); hub STATUS armed bit False->True at 14.649 s (+0.63 s).
- disarm: MSP 1->0 at 24.201 s (+0.18 s); hub armed True->False at 25.033 s (+1.0 s).
- arming_disable names empty throughout (after the first 3.7 s RX_FAILSAFE). Final snapshot: `armtest_final_snapshot.json`.

## Files
diff_all_before/after(.txt), diff_all_after2.txt (INTERMEDIATE evidence from an earlier flash, wiped config; not the final state; superseded by diff_all_after.txt), replay_input.txt, replay_log*.txt, flash_log*.txt, image_sha256*.txt,
invariants*_after.txt, voltage_before.txt, bfcli.py, armtest.py/_log.csv/_events.json/_final_snapshot.json, link_20261108-103352/ (events, result, msp.log).

## Final fix-up session (12:25-12:55, drone on USB, no battery, hw lock held, backend stopped)
- Battery check: CLI `status` line "Voltage: 1 * 0.01V (0S battery - NOT PRESENT)" (not bf_msp.parse_analog vbat_dv, which is misaligned).
- LEDs-off invariant: `resource LED 1 C13` was still assigned (only RX_SPI_LED was NONE). Now `resource LED 1 NONE` + `save`; persisted across reboot
  (diff_all_after.txt has `resource LED 1 NONE`, `RX_SPI_LED 1 NONE`; LED_STRIP feature off: dump shows `feature -LED_STRIP`).
- CLI pitfall: the FIRST command after the `#` handshake is silently swallowed (bfcli.py / my first attempts lost `resource LED 1 NONE` and `save`); send a dummy `version` first. `save` reboots, the port vanishes.
- Final `diff_all_after.txt` (replaces stale one) + `version_after.txt` (version, resource show, feature, status). Build 4.2.11 Nov 8 2026 11:20:01 (a7c24987); gyro ICM20689 detected.
- Invariants verified: frsky_spi_tx_id 66,178; frsky_spi_offset -32; hop table 0,57,112,...,228,0,0,0 unchanged; feature TELEMETRY enabled; LEDs off.
- Before/after diff (expected): `before` is a full dump from a stock image without target defaults, `after` is a diff against the patched target's
  defaults, so the default-equal lines (resources, gyro_1_*, battery/current meter, system_hse_mhz, beeper, `feature TELEMETRY/OSD/RX_SPI` etc.) disappear
  from after while still being active (`feature` shows TELEMETRY OSD AIRMODE RX_SPI ...). Only real additions: `resource LED 1 NONE`. Link-relevant sets unchanged.
- Radio sanity (tlm_listen link 20 s, ESP32 RTS-reset + 4 s): 36/46 triggers answered (78%), hub decodes STATUS 18 (ANGLE + arming disabled), ACC -26/-35/1004 mg, gyro/attitude IDs present.
  Run: results/telemetry/20261108-125332-link. diff_all_after2.txt is intermediate evidence from an earlier flash (wiped config), kept only for history.
