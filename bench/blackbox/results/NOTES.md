# Blackbox on the drone: bench notes, 2026-11-08 (Track 3)

## MORNING STEP after USB replug (do this first)

When this session ended, the FC (MATEKF411RX, patched Betaflight 4.2.11 `a7c24987`, built Nov 8 2026 11:20:01) was
hung. It did not answer MSP, the CLI or radio telemetry. It needs a physical USB unplug and replug. Blackbox-on-VCP
is still **enabled and saved**. Revert it: while it is on, every arm/disarm leaves the USB port silent (see below),
which breaks MSP and `d8tx.server`.

Take `/tmp/d8tx-hw.lock` first and stop `d8tx.server` (`pkill -f d8tx.server`). Then, from `bench/blackbox`:

```
P=/dev/cu.usbmodem0x80000001; E=results/bench
# 1. state now: expect exactly one line of difference from the pre-blackbox diff ('> serial 20 129 115200 57600 0 2000000')
.venv/bin/python bbcli.py diff $E/diff_all_morning.txt --port $P
diff $E/diff_all_before.txt $E/diff_all_morning.txt
# 2. revert (writes 'serial 20 1 115200 57600 0 115200' + blackbox defaults, then save/reboot)
.venv/bin/python bbcli.py apply config/revert_serial_vcp.txt --save --log $E/revert.log --port $P
# 3. verify: no difference at all from the pre-blackbox diff
.venv/bin/python bbcli.py diff $E/diff_all_reverted.txt --port $P
diff $E/diff_all_before.txt $E/diff_all_reverted.txt && echo REVERTED-OK
```

Wait for the port to come back between steps (`until ls $P; do sleep 0.5; done`), because each `bbcli.py` call
reboots the FC. Only the `# version` header line may differ in step 1 or 3 (for example, after a reflash).

Plan invariants to recheck in `diff_all_reverted.txt`, all of which held before and after the change tonight:
`set frsky_spi_tx_id = 66,178`, `set frsky_spi_offset = -32`, the bound `frsky_spi_bind_hop_data` (0,57,112,…,228,0,0,0),
`resource LED 1 NONE` and `resource RX_SPI_LED 1 NONE`. Also run `.venv/bin/python bbcli.py run feature --port $P`:
it must list TELEMETRY and must not list LED_STRIP. Tonight it showed
`Enabled: TELEMETRY OSD AIRMODE RX_SPI ANTI_GRAVITY DYNAMIC_FILTER`.

## Result in one paragraph

The tool chain works end to end on a real Betaflight 4.2 log. One armed session (about 15 s of scripted roll, pitch
and yaw sweeps) decoded with 0 failed frames at 954 Hz, and rcCommand follows the scripted sticks (±300), except the first ~0.9 s: rxSignalReceived=0 from 0.081 to 0.922 s, so the first roll ramp is missing (roll jumps 0→104→244 in 8 ms); probably a link or USB-reset gap.
Logging to the **shared USB VCP is not usable as a routine setup on this FC/Mac**, though. On F4, Betaflight 4.2
reopens the VCP with `usbVcpOpen()` whenever the port changes owner: on arm (blackbox takes it from MSP) and on
disarm (MSP gets it back). That function pulls D+ low for 200 ms and calls `USBD_Init()` again
(`drivers/serial_usb_vcp.c:219`, `drivers/usb_io.c:69`). macOS does not re-enumerate after that, so the port goes
silent. A host-side libusb port reset (`usbreset.py`) does bring it back. Data flowed after one reset per arm, but
the start of the header had already been dropped. A later run reset every 1.5 s of silence, which wedged the FC
completely (no USB, no radio telemetry).

## Timeline and commands (lock held 12:54–13:24)

1. Lock acquired at 12:54:23; `pkill -f d8tx.server`.
2. `bbcli.py diff results/bench/diff_all_before.txt`. The FC had been left **in CLI mode** (probably by Track 2's
   flash), so `#` only echoed and `bbcli` failed with "no CLI prompt". I fixed `bbcli.enter()` (below).
3. `bbcli.py apply config/enable_serial_vcp.txt --save --log results/bench/apply.log`, then `diff_all_after.txt`.
   `diff before after` showed only `> serial 20 129 115200 57600 0 2000000`. The `set blackbox_*` lines equal the
   defaults, so they do not appear in the diff.
4. Battery check, using the new `bbcapture.battery_readings()`:
   `{'analog_dv': 0.0, 'analog_cv': 0.01, 'cells': 0, 'batt_dv': 0.0, 'batt_state': 3, 'batt_cv': 0.01}`, worst
   case 0.01 V. CLI `status` gave `Voltage: 1 * 0.01V (0S battery - NOT PRESENT)`. That confirms USB power only.
   (`bf_msp.parse_analog` also read `vbat_dv=0` here. The 241 reading was not reproduced.)
5. `bbcapture.py serial --sessions 2 --idle 20` plus `bbarm.py --sessions 2`: **0 bytes**. MSP was dead after the arm.
6. Probes (`results/bench/probes/`): MSP_STATUS polled during the link showed `arming_disable` going from
   `RX_FAILSAFE` to `[]` (armable), and MSP stopped answering at the arm edge. Reopening the tty never got data. A
   libusb reset (pyusb `dev.reset()`, which reports "Entity not found" but works) changes the IORegistry device id
   and brought MSP back once while disarmed.
7. **session1** (13:10): `bbwatch_reset.py` (poll MSP; on loss, one USB reset; then read) plus
   `bbarm.py --sessions 1 --lead-s 4`. Arm sent at 1794161402.42, MSP lost at +0.77 s, reset, port reopened at
   +1.9 s. The first bytes received were mid-header (`…,0,0,0\nH Field S predictor…`). 363,085 bytes raw.
8. Two-session run (13:12) with a reset on every 1.5 s of silence: the stream stopped after about 1 s. The repeated
   resets produced nothing, and afterwards the FC answered neither USB (MSP/CLI, even after resets and an arm/disarm
   cycle) nor radio telemetry (21 triggers, 0 replies, where it had answered at 13:00). The ESP32 itself answered
   INFO. Lock released at 13:24, and the parent was told.

## session1 numbers (`results/bench/`)

| | |
|---|---|
| raw capture | `session1.raw`, 363,085 B, header tail + 360,542 B of frames, no LOG_END (lost at disarm re-init) |
| reconstructed log | `bb_session1_reconstructed.bbl` (364,216 B), made by `reconstruct_header.py` (header start rebuilt, marked `H Comment:RECONSTRUCTED`) |
| decode (C, blackbox-tools d89f96b) | 13,655 frames (428 I, 13,227 P, 6 S), 0 failed, 14 iterations unreadable at the start; 954 Hz, 25,451 B/s; `decode_stderr.txt` |
| duration | 14.31 s logged; frame dt median 1030 µs, max gap 15.6 ms |
| header facts | looptime 125 µs (8 kHz gyro), pid_process_denom 2 (4 kHz PID), I interval 128, P interval 4 (1 kHz rows), P ratio 32, minthrottle 1070, motorOutput 177..2047, DSHOT (protocol 7), debug_mode 0 |
| "iterations missing 75%" | expected: the known bare-integer `P interval` quirk (README); time and data are correct |
| columns | loopIteration, time, axisP/I/D[0..2], axisF[0..2], rcCommand[0..3], setpoint[0..3], vbatLatest, amperageLatest, rssi, gyroADC[0..2], accSmooth[0..2], motor[0..3] + S flags |
| plot | `bb_session1_reconstructed.01.png` (gyro, setpoint, rcCommand, motors vs time); CSV `…01.csv` |
| sticks sent | `session1_sticks.csv` (t_unix, segment, arm, ch1..8 at ~100 Hz) |

Check against the script: rcCommand[0..2] reach -300..+313 / -295..+300 / -300..+300, tracing the 0.75 s ramp, hold,
ramp and return shapes for roll, then pitch, then yaw, in order (plot). Setpoint follows at about ±170 deg/s (yaw
curve from rc_expo). gyroADC is ±1 deg/s, because the drone sits still on the bench. vbatLatest is 0..12 raw
(no battery). Motors swing from 176 to about 2047 with props off: the PID I-term and airmode wind up with no
feedback. The ESCs are unpowered, so nothing moved.

The reconstruction is valid because the rebuilt start (Product, Data version, intervals, Field I/P definitions,
Field S name and signed) follows BF 4.2 `blackbox.c` field conditions for this config: yaw D is 10, so `axisD[2]` is
present; the current meter is ADC, so `amperageLatest` is present; `rssi` is present. That variant decodes with 0
failed frames and a 954 Hz rate. The variants without `rssi` or without `axisD[2]` decode to garbage (30 Hz, 99%
missing). The captured header tail confirmed the S-field predictors and encodings.

## Issues / unresolved

- **FC hung; needs a replug** (top of file). The cause is probably the repeated host USB resets during or after the
  VCP re-init, but this is not proven.
- **Blackbox over a shared USB VCP is not workable here** without a host reset per arm, and even then the start of
  the header is lost. Options: log to a UART with an OpenLager or a USB-serial adapter (needs hardware), or capture
  on Linux, which may re-enumerate after the D+ pulse (untested). `blackbox_baud` below 1M throttles only the header
  and does not fix this.
- rcCommand[3] stayed at 1000 to 1001 while the script sent throttle up to 1150, yet motors ramped in the throttle
  segment. Explained by the validator, so this is expected: rateprofile 0 has thr_mid=0 and thr_expo=100, so the throttle curve is 1000+i³ (rc.c generateThrottleCurve). With mincheck 1050, 1150 maps to tmp=105, which gives rcCommand 1001. The motor ramp comes from I-term windup under airmode; flight mode was ARM|ANGLE.
- The Python parser emits 14 extra start-of-log frames (iterations 54546–54559) that blackbox_decode drops, and misses iteration 54660. All shared cells match the C decoder.
- No LOG_END was captured, so `bbcapture.record()` would rely on its idle timeout.
- Installed on the Mac for this: `brew install uhubctl` (pulls in libusb; the hub has no per-port power switching,
  so uhubctl itself is useless) and `pyusb` in `bench/blackbox/.venv`. `usbreset.py` needs `/opt/homebrew/lib/libusb-1.0.dylib`.
- The ESP32 sometimes stopped answering after `D8Link` opened its port (likely boot-mode glitch from DTR/RTS on open).
  An EN reset (DTR low, RTS pulse) recovers it; `bbarm.py` now does this on INFO timeout.
