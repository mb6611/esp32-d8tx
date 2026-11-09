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

# Why the drone did not reply: 2026-11-07 22:01 - 2026-11-08 00:26

Drone on USB, stock Betaflight 4.2.11 with feature TELEMETRY (no config change), arm channel low, never armed.
All runs: `tlm_listen.py link --stream --ack --msp /dev/cu.usbmodem0x80000001 --seconds 60 --every 48 --power 127 --cap-us 9000`
plus the flags in the table. Firmware adds per-capture timing fields, a ch8 trigger marker, and an optional re-trigger (see below).

**Cause: our carrier was ~35 kHz above the drone's receive frequency at FOFS -50 kHz, and the drone lost ~15-20% of our
packets, trigger packets included. FOFS -75 kHz fixes it: 97.8-100% of triggers answered (vs 82% at -50 kHz back to back).**

Evidence:
1. **The drone never decoded the missed trigger packets.** `--mark` sets ch8 to 1500 us on trigger packets only (1000 otherwise, below
   every aux range) and `--msp-rc-hz 100` polls MSP_RC (~55 Hz in practice, the USB VCP round trip is 16 ms). `host/tlm_why.py` checks
   whether the marker reached rcData near each trigger. Over the 11 marker runs: answered triggers showed the marker 72-86% of the time
   (that is the MSP sampling coverage), missed triggers 1 of 88. So a miss is the drone losing our packet, not a reply it failed to
   send or one we failed to hear. Betaflight's reply conditions (cc2500_frsky_d.c) are only: CRC ok, txid match, byte3 % 4 == 2,
   then a reply 1380 us later on the next hop channel. CCA is off (MCSM1 0x0C), and nothing depends on earlier packets or the hub state.
2. **Timing is not it.** New `gap` field = packet start minus the previous packet start minus 8994 us. |gap| median is ~30-55 us for both hits and
   misses, and misses are not later (60 s runs: max 130-360 us, `gap200` = 1 in the last 4 runs). The trigger slot is not delayed. A 16-bit tail after the CRC
   (`--tlmx "16 0"`, 220528: 81%) changed nothing.
3. **Frequency is it.** At FOFS -50 kHz the reply sits ~34 kHz below our LO, so our packets land ~34 kHz above the drone's
   synthesizer. The CC2500 FOC limit with FOCCFG 0x16 is about ±BW/4 ≈ ±34 kHz, and our hard 2-FSK deviation is 39 kHz. FOFS sweep (139 triggers each):

| Run | FOFS kHz | Caught | Notes |
|---|---|---|---|
| 20261107-220144 | -50 | 119 (85.6%) | marker on misses 0/20 |
| 20261107-220528 | -50 | 113 (81.3%) | +16-bit tail on triggers |
| 20261107-220730 | -50 | 112 (80.6%) | probes on |
| 20261107-221227 | -65 | 138 (99.3%) | |
| 20261107-221330 | -70 | 133 (95.7%) | |
| 20261107-221012 | -75 | 137 (98.6%) | |
| 20261107-221535 | -75 | 138 (99.3%) | |
| 20261107-221432 | -80 | 138 (99.3%) | |
| 20261107-220901 | -85 | 131 (94.2%) | reply CFO +2..+6 kHz |
| 20261107-221115 | -95 | 130 (93.5%) | |
| 20261108-002322 | -75 | 136 (97.8%) | plain run (no marker/MSP_RC); tlm_misses: 2 a, 1 b (interfered reply) |
| 20261108-002524 | -50 | 114 (82.0%) | control right after; tlm_misses: 20 a, 2 b, 3 c |

   The -65 to -80 kHz plateau is centred near -75 kHz. At -75 kHz the reply CFO is -4 to -16 kHz. The ch 4 -> 59 outlier from MISSES.md went away
   with the offset (k=2928 still missed once in 002322). The `probe` mode (one marked plain data packet with a silent slot after it, half way
   between triggers) gave marker/coverage ratios of 0.79-1.06 that did not follow FOFS cleanly, so it is weak evidence and is not used above.
   The owner's ~97% data-packet figure fits FOFS ≈ -75 kHz. At -50 kHz the drone also lost ~15-20% of its control packets.
4. Two retry runs were cut short by the Mac going to sleep on battery (capture stalled mid-stream; pmset log). Those runs were deleted. Bench runs need the
   Mac awake (`caffeinate -dimsu` helped once the display was on).

**Re-trigger (fallback, `--retry N`, stream mode only):** after each capture the firmware counts 0.5 ms blocks in 2.0-7.5 ms with mean
I²+Q² > 2e5 (int16, scaled by (dec/32)²). Offline over 586 captures of 2026-11-07, every reply had 11/11 and every no-reply had ≤ 8.
With fewer than 9, it drops the capture (one `EV tlm_drop` line) and sends the same tid again at the next free slot (k+2). Betaflight's re-request
rule resends the same hub bytes, so no hub data is lost.

| Run | FOFS | retry | Requests caught | Per trigger attempt |
|---|---|---|---|---|
| 20261108-002208 | -50 | 1 | 138/138 (100%) | 138/146 (94.5%), 8 re-triggers, all 8 answered |
| 20261108-002423 | -75 | 1 | 139/139 (100%) | 139/139 (100%), no re-trigger needed |
| 20261108-002322 | -75 | 0 | 136/139 (97.8%) | same |

Recommendation: use FOFS -75000 (the app currently defaults to -63000 in app/src/App.tsx, and tlm_listen examples use -50000). Keep `--retry 1` for telemetry.
The drone's frequency drifts by a few kHz between sessions (the -50 kHz first-try rate varied 81-94%), so a centred offset matters more than retries.
