# D8 telemetry reply capture: battery-on trial 2026-11-07 21:10

Command (from bench/d8-tx/host): `tlm_listen.py link --seconds 20 --every 48 --power 127 --fofs -50000`
Run: 20261107-211006-link (arm channel low; drone on battery, stock Betaflight, no config change).

Result: WORKS. 26 of 46 trigger slots captured a CRC-valid 18-byte 0x11 frame from txid 66,178.
The reply came on the NEXT hop channel (Betaflight calls nextChannel(1) before replying).
- Unkey to capture start: 207-368 us. Capture length 10.3 ms at 500 kS/s. lost=0 bad=0.
- Reply start: 1.34-1.51 ms after the trigger packet (Betaflight nominal 1380 us). CFO about -30 to -33 kHz.
- A1=75, A2=26 (raw), RSSI byte 71-76 (decoder's dBm label), telemetry id echoed correctly.
- Hub byte count = 0 in every frame. FrSky hub data has not been seen yet (open question).
- Misses: slots 432, 672-720, and 816-1392 (one long gap) plus scattered ones; cause not investigated.
- LINK timing during the run: late_max 129 us, retune_max 374 us.

# Catch rate and hub data: follow-up 2026-11-07 21:18-21:29

Drone on USB power this time (A1 reads 0, expected), stock Betaflight 4.2.11, arm channel low, no config change.
Same `--power 127 --fofs -50000 --every 48`. MSP (RSSI, arming flags) logged at ~7 Hz to `msp.log` in each run dir.

| Run | Firmware/host mode | Caught | Longest miss run | RX failsafe (MSP rows) |
|---|---|---|---|---|
| 20261107-211801-link (20 s) | old: blocking int16 dump, tid +1 per trigger | 11/46 (24%) | 14 | 166/174 |
| 20261107-212358-link (60 s) | old, same | 56/139 (40%) | 10 | 318/400 |
| 20261107-212508-link (60 s) | new: `--stream --ack --cap-us 9000` | 121/139 (87%) | 2 | 16/403 (first ~2 s only) |
| 20261107-212744-link (60 s) | new + deferred int8 conversion (late_max 722 -> 166 us) | 114/139 (82%) | 2 | 16/400 (first ~2 s only) |

Causes found:
- **Misses and the long miss runs = the dump stalled the link.** The old firmware stopped transmitting while it sent the
  20 KB capture over the UART (~0.22 s, ~24 slots, at each trigger). Betaflight dropped into RX failsafe for most of the
  run (MSP RX_FAILSAFE, RSSI 0), then lost the hop phase and took seconds to find it again. Now the capture is int8
  (~9 KB) and goes out in the ~1.9 ms gaps between packets. LINK sends every slot except the reply slot
  (6575 slots in 60 s), and the RX stays out of failsafe once Betaflight's ~2 s recovery after link start is over.
- **Reply-slot timing was already right:** slot k+1 is never sent (the reply runs ~1.4-8.1 ms after the trigger
  packet ends, on k+1's channel). The 9-10 ms capture covers it, and the link resumes at k+2. That matches Betaflight:
  `STATE_TELEMETRY` resets its 9 ms timeout at reply start, then it moves to k+2's channel ~0.6 ms before our packet.
- **Remaining ~13-18% misses are single, scattered, and not tied to any channel** (21 channels missed once out of 3-4
  visits each, never twice in a row). The link stays in sync during them: RSSI steady around 548, no failsafe. The
  captures show no reply energy (median rms ~21-29 vs ~60 for hits), so the drone did not reply. The most likely cause
  is that it lost that trigger packet, which fits the ~5-7% single-channel loss measured earlier, but this is not proven.
- **Hub count 0: the receiver's telemetry feature is off.** MSP_FEATURE_CONFIG = 0x32450000, so FEATURE_TELEMETRY
  (bit 10) = 0. Betaflight's `frSkyDInit` only enables hub data when that feature is on, so frame[6] is always 0 no
  matter which id we send. No ACC X/Y/Z can be decoded without changing the drone config (not done). The id rule was
  also wrong: tid went +1 per trigger even after a miss. It is now ack/resend (`--ack`: host sends `TID` = id+1 after a
  decoded reply, else the same id). The runs confirm the rule (tid repeats after every miss). The hub decoder is
  `host/d8hub.py` (0x5E frames, 0x5D stuffing, ACC 0x24-0x26 in g), with offline tests `host/test_d8hub.py`, which
  include a model of Betaflight's `appendFrSkyHubData`.

# Hub telemetry with FEATURE_TELEMETRY on: 2026-11-07 21:32

Config change (owner-approved, left enabled): CLI `feature TELEMETRY`, `save`. `bf-diff-before.txt` vs
`bf-diff-after.txt`: the only difference is the added line `feature TELEMETRY`. Revert if ever needed: `feature -TELEMETRY`, `save`.
Drone on USB power, arm channel low (never armed).

Command (from bench/d8-tx/host): `tlm_listen.py link --stream --ack --msp /dev/cu.usbmodem0x80000001 --seconds 60 --every 48 --power 127 --fofs -50000`
Run: 20261107-213222-link.

Result: hub data WORKS. 119/139 triggers caught a reply (86%). hub_bytes=836, hub_frames=196, link late_max 384 us,
retune_max 415 us, RX failsafe only in the first ~2 s (15/400 MSP rows).
- Typical hub payload: `5e2400005e2500005e26` then `00005e` in the next reply. Frames split across replies reassemble
  correctly (ack/resend keeps the stream intact).
- Decoded values (whole run): ACC_X=0 x51, ACC_Y=0 x51, ACC_Z=0 x50, plus TEMP1/RPM/FUEL/VOLT/VOLTAGE_AMP_BP/AP/CURRENT=0
  x6 each and one time frame (HOUR_MINUTE=256, SECOND=0, sent every 5 s).
- **ACC_Z = 0, not 1 g, is right for Betaflight 4.2.** frsky_hub.c sendAccel sends
  `((int16_t)(accADC * acc_1G_rec)) * 1000`: the cast truncates to whole g before the x1000. MSP_RAW_IMU at the same time
  read acc = (-8, 39, 510) in MSP units (scale 4 -> Z ~0.996 g), which truncates to 0. So hub ACC only ever reads 0 / +-1000 /
  +-2000 milli-g; it shows 1 g only once the Z reading reaches a full 1 g. The decoder (`host/d8hub.py`) is correct;
  its acc_g docstring and test were updated to this encoding.
- VOLT/current/fuel 0 is expected on USB power.
