# Why telemetry triggers miss: offline analysis of 212358 / 212508 / 212744 (2026-11-07)

Offline only (saved captures, no hardware). Script: `bench/d8-tx/host/tlm_misses.py` (test:
`bench/d8-tx/tests/test_tlm_misses.py`). To reproduce, from the repo root:

    R=bench/d8-tx/results/telemetry
    ../auto-drone/stage0/.venv/bin/python bench/d8-tx/host/tlm_misses.py \
        $R/20261107-212358-link $R/20261107-212508-link $R/20261107-212744-link --json /tmp/misses.json

Method, per capture:
- **Energy:** 100 µs block power against the run's receiver noise floor (median quiet level, int16 units
  after undoing the int8 `sh` shift). A burst is ≥ 10 dB for ≥ 0.5 ms.
- **Presence:** the drone runs with telemetry off on USB, so every reply is fixed except the RSSI byte (`11 42 b2 00 00 RR 00 tid 00…`).
  `template_corr` correlates the discriminator output with those ~190 known bits (RSSI byte and CRC left out). Every caught reply
  scores ≥ 0.75. Every capture with no reply scores ≤ 0.12 (124 captures). The threshold is 0.25, so this finds a reply
  even where sync or CRC fails.
- **Classes:** hit = the stock `decode_capture` finds a CRC-valid telemetry frame; (a) = no burst and no
  template match; (b) = a burst inside the window but no CRC-valid frame; (c) = a burst touching the window edge and shorter than a whole reply (6.70 ms).
  For b and c, a second check says whether the energy is a reply (template match) or interference.
- **Margins on hits:** sync errors; soft-bit eye (integrate-and-dump value × the correct bit sign, ÷ deviation:
  1.0 is ideal, ≤ 0 is a bit error); band fraction (share of power within ±70 kHz of −35 kHz); envelope CV.

## Counts

| Run | Mode | Triggers | Hit | (a) no reply energy | (b) energy, no CRC | (c) cut by window | Relaxed decode recovers |
|---|---|---|---|---|---|---|---|
| 212358 | old blocking int16 | 139 | 56 | **81** | 1 (interference) | 1 (interference) | 0 |
| 212508 | stream int8 + ack | 139 | 121 (87.1%) | **16** (11.5%) | 2 (interference) | 0 | 0 |
| 212744 | stream int8 + ack | 139 | 114 (82.0%) | **21** (15.1%) | 3: 2 reply under interference, 1 interference | 1 (interference) | 1 |

- **(a) is almost all of it: 118 of 126 misses.** In those captures the template correlation is ≤ 0.10, against 0.75–0.91 for
  real replies, which are 29–39 dB over the floor. So no reply is hiding under the noise: the drone did not transmit on the
  frequency we were listening to.
- The b/c interference bursts are wideband: band fraction 0.09–0.30, spread over ±250 kHz, lasting 0.6–2.6 ms or all 9 ms.
  The look fits Wi-Fi or BLE, but the source is unknown. Odd detail: slot k=1152 (listen ch 97) hit a burst in **both** stream runs.
- In two captures the drone did reply but interference broke the frame. Both are in 212744, on listen ch 112 (2426.4 MHz):
  - k=2304: correlation 0.60. The relaxed decode recovers it only with a single-bit CRC fix at one carrier shift (−40 kHz).
  - k=4560: correlation 0.32, with 2–3 bit errors under a burst about 3 dB stronger than the reply. Not recoverable.
- (c) caught no reply in any run. No reply ever falls outside the window.

**What a better host decoder would buy: at most 1 of 417 captures (0.24%).** Trying the stock decoder + `fix1` +
a 5 kHz carrier grid (−60…−10 kHz) over all three runs recovers only 212744 k=2304, at twice the CPU. Even that works at
only one exact setting, so it is not robust. `tlm_listen.py` was left unchanged.

## Caught replies: level, carrier, timing, margins

| | 212358 | 212508 | 212744 |
|---|---|---|---|
| CFO (reply vs RX LO), min / median / max kHz | −42.4 / −39.0 / −36.0 | −38.7 / −34.3 / −31.2 | −39.3 / −33.6 / −30.2 |
| Reply start after unkey (ms) | 1.66–1.75 | 1.66–1.76 | 1.66–1.75 |
| Window room after reply end (ms, 5th pct) | 1.7 (cap 10 ms) | 0.7 (cap 9 ms) | 0.6 (cap 9 ms) |
| SNR over floor, 5th–95th pct (dB) | 35–38 | 32–34 | 30–34 |
| Reply rms / peak \|I\|,\|Q\| (int16 sums, full scale ±16384) | 2080 / ≤ 2823 | 2200 / ≤ 2688 | 2050 / ≤ 3264 |
| Sync errors 0 / 1 / 2 | 54 / 1 / 1 | 115 / 4 / 2 | 111 / 1 / 2 |
| Soft eye min, 5th pct (mean) | 0.68 (0.90) | 0.66 (0.89) | 0.66 (0.89) |
| Sign errors before CRC | 0 | 0 | 0 (1 in one hit; another cutoff decoded it) |

- **Level:** gain code 40 gives replies 30–39 dB above the noise, peaks ≤ 20% of full scale, a constant envelope (CV ≈ 0.09)
  and no clipping. In stream mode the int8 shift is sh=5 on every reply, which leaves the noise at about 1 LSB. Quantisation
  costs nothing at this SNR. **Gain is not a cause of misses.** The captures with no reply ship with sh=0–1 because the
  firmware fits the shift to their peak, which is noise.
- **Carrier:** the reply sits 30–42 kHz below the RX LO (with FOFS −50 kHz). It is the same on every channel (per-channel
  means −32 to −36 kHz) and drifts by a few kHz between runs (old run −39, later runs −34). The stock shift grid
  (−50/−25 kHz) covers it.
- **Margins:** sync errors are almost always 0, the eye is ≥ 0.58, and there are no slicer errors before CRC. On a hit the
  decoder has a lot of margin. Misses are not near-threshold decodes.
- **Timing:** the reply starts 1.66–1.76 ms after unkey (jitter 0.1 ms) and ends about 8.45 ms after unkey. The capture
  ends 9.2–9.3 ms after unkey (turn 0.20–0.41 ms + 9.0 ms), which leaves ≥ 0.75 ms spare.
- **Firmware timing does not predict misses:** turn_ns, late (always 8) and work are the same for hits and misses.

## Pattern in the (a) misses

- **Listen ch 59 (trigger ch 4, 2405.2 MHz → reply on 2421.7 MHz) misses 5 of 6 times in the stream runs (8 of 9 counting
  212358).** If misses were independent at 13.3%, the chance of that is 0.0002 per channel, or 0.01 over 47 channels. No other channel stands out (≤ 2 of 6). The earlier
  ESP32 hop test on the CC2500 rxdiag had no weak channel (`results/hop/esp_hop/summary.md`). The cause is open:
  - the drone may lose our ch-4 packets (its calibration at 2405.2 MHz), or
  - it may send the ch-59 reply far enough off frequency to fall outside ±250 kHz.
  Some identical k values miss in several runs (528, 672, 5184), but that is the same table position, not a timing effect.
- The rest are scattered single misses (sometimes 2 in a row with the same tid; that is expected by chance), and one per stream run comes during
  Betaflight's start-up failsafe (k=144, 288).

## Recommendations (firmware / bench)

1. **The ~13% (a) misses are the main gap to the 97% target, and no receive-side change can recover them.** The drone did not
   transmit where we listened. Suggested next bench steps:
   - A run at `--dec 16` (1 MS/s, ±500 kHz) to rule out off-frequency replies, especially on ch 59.
   - A run with `every 47`, which keeps the trigger on one channel, to compare trigger ch 4 with a control channel.
2. **Re-trigger on the firmware side.** The reply is 30 dB over the floor, so an on-chip energy check is reliable: mean
   power over 1.4–8 ms of the capture vs the first 1 ms, or vs a fixed floor of about 30 rms int16 at gain 40. If there was no
   reply, send the same tid again at k+2 (or the next free slot) instead of waiting about 48 slots for the host's `TID`.
   With independent misses, two tries give about 1 − 0.13² ≈ 98% per request. Betaflight replies to any packet whose byte 3
   % 4 == 2, so this needs no drone change.
3. **RX gain:** keep a manual code around 40 (30–50 is fine). There is plenty of headroom: peaks are ≤ 20% of full scale at
   30+ dB SNR. Do not use AGC.
4. **Listen frequency (optional):** shift the RX LO by about −35 kHz from the TX FOFS (this needs a separate RX offset; FOFS
   is shared today). That centres the reply, so the narrow ±35–40 kHz filters reject more of the wideband interference.
   It would have helped at most the 2 interfered replies. The host decoder already handles the offset.
5. **Capture window:** 9000 µs is enough (≥ 0.75 ms spare after the reply). Do not go below about 8600 µs. A longer window
   would not have caught anything more: no (c) miss was a reply.
6. **Host decoder:** no change needed. The 1 of 417 that `fix1` + a fine grid recovers is not worth twice the CPU.
