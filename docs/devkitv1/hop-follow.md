# Hop-following D8 receive (receive only)

Goal: decode the FrSky D8 transmitter on all 47 hop channels (~111 packets/s) instead of
one channel (~2.4 packets/s), and feed the result to `d8live`.

**Result (2026-11-05, one board, tx id 66,178):** a 159 s `d8live --follow` run decoded
**108 CRC-valid packets/s**, **97.7 % of hop slots** (17 155 of 17 557), with **0 lock
losses** and 0 lost stream samples. 46 of the 47 channels decode at 97–100 %. One channel
(slot 33, 2411.435 MHz) almost never passes CRC, which caps the total at 97.9 %. When the
lock was knocked off on purpose, the follower noticed after 47 hops (0.44 s) and re-acquired
0.11–0.37 s later.

Firmware: `main/targets/esp32/hop_follow.h` (included by `receiver.c`) and the tagging in
`iq_stream.c`. Host: `host/esp32sdr/hopfollow.py` (protocol), `host/esp32sdr/d8follow.py`
(follower, CLI `esp32sdr d8follow`), `d8live --follow`. Tests: `host/tests/test_d8follow.py`
(simulated hopping tx and firmware). Retune method: `fast-hop.md` (mode 1).

## Design

The firmware owns the timing; the host owns the decisions.

- **Schedule on the sample clock.** The host loads the 47 LO frequencies (`HOPTAB`). During
  the IQS run it sends `HS slot pair period`, which means: at stream pair index `pair`
  (16 MS/s), retune to `slot`, then step to the next slot every `period` (in milli-pairs).
  An `esp_timer` one-shot runs the retune on core 0 in the esp_timer task. It converts
  sample indices to time through `iq_stream_pair_now()`: an esp_timer estimate, corrected
  to the exact ring position by `DUMP_STATUS`. Because the schedule is defined in stream
  samples, firmware jitter does not accumulate, and the host can predict hop times in
  stream sample units.
- **Tagging.** Each retune records the pair index where the call starts and where it ends.
  Stage 2 cuts the output frame at `ceil(ps/dec)`. The next frame has flag bit 2 set (a
  channel segment starts here), flag bits 4..7 = (retune end − start + 16 samples) / 8 to
  blank, and the header `shift` byte = slot. While tagging is active, every frame has flag
  bit 3 set, and its `shift` byte carries the slot. Frames shrink to roughly one hop (~2250
  samples). The extra headers add about 3 kB/s, well inside the link budget.
- **In-stream commands.** With a table loaded, the IQS run reads host lines: an empty line
  stops the run (as before: `STOP_BYTE` is `\n`), and `HS`/`HA`/`HP`/`HX` go to the hop
  code. There are no replies. The effect shows up in the tags. Without a table, IQS behaves
  as before: any byte stops it. This adds one function to `burst_serial`:
  `burst_serial_read` (non-blocking).
- **Host follower** (`HopFollower`):
  - *acquire*: hold slot 1 (channel 57, 2421.032 MHz) and search it continuously with
    `LiveDecoder`.
  - First CRC-valid packet: set `a` = its preamble time. Hop *m* carries the packet at
    `a + m·P`, on slot `(1 + m) mod 47`. Send `HS` so that each retune lands 1.15 ms before
    the predicted preamble, the middle of the ~2.3 ms gap. The first scheduled hop is
    ≥ 45 ms ahead of the newest received sample, to cover command latency.
  - *locked*: decode each tagged segment on its own (blank skipped, `StandardDecoder`).
    Check that the packet's slot matches the schedule. Fit `t = a + m·P` over the last
    141 packets. Re-send `HS` when the fit moves the hops 10 slots ahead by > 15 µs (at
    most every 0.25 s). That came to about one `HS` every 15–20 s.
  - *lost*: no CRC-valid packet for 47 hops sends `HX 1` and returns to *acquire*.
- Channel table: `f = (2404 MHz + n·299.93 kHz)·(1 − 26.4 ppm)`, with n from the bind
  table. The LO is that frequency − 4 MHz (`--mode 2`). The ppm comes from the measured
  2421.032 vs nominal 2421.096 on channel 57. It is applied the same way to every channel
  and centres them all: the burst CFOs seen were about 0.3–1.8 kHz.

### Commands

| Command | When | Meaning |
|---|---|---|
| `HOPTAB i khz…` | idle | LO kHz for slots i, i+1, …; ≤ 15 per line, ≤ 64 slots |
| `HOPCLR` / `HOPTAB?` | idle | clear table / `HOPTAB n` |
| `HOPSTAT?` | idle | after a run: `hops late_max_pairs skipped qfull retune_max_pairs` |
| `HS slot pair period_mp` | in IQS | start schedule; a start in the past advances by whole periods and slots |
| `HA dpairs` | in IQS | shift schedule (signed) |
| `HP period_mp` | in IQS | period from the next hop on |
| `HX slot` | in IQS | stop schedule, retune to slot now (tagged) |

## Step 1: retune during IQS (no transmitter needed)

`host/tools/probe_hopstream.py` (logs in `bench/hop-follow/retune-in-stream.txt`). The
board's 40 MHz crystal harmonic at 2400.000 MHz served as reference. Slot 0 put it at
−50 kHz; slot 1 was 10 MHz away. The probe alternated every 9 ms for 5 s, at 1-bit dec 64,
mode 2, gain 40.

- **Stream integrity:** 512–513 retunes, 0 gap samples, 0 bad CRC, IQSEND
  `abandoned 0, drops 0`, `late_max` 10 pairs. The retune on core 0 does not disturb the
  app-CPU ring.
- **Timing:** retune call ≤ 5218–6352 pairs (326–397 µs) in the worst case. Timer
  lateness ≤ 1489 pairs (93 µs). Segment spacing median 2250.0 samples (exact), minimum
  2220 (one late hop).
- **Transient:** the old channel's line is gone 16 samples (64 µs) after the tag. The new
  line appears at 56 samples (224 µs) and is within 10 % of its steady level at
  72–80 samples (288–320 µs). The tag's blank field (retune end + 16 samples) came out at
  72–120 samples. Since the retune sits ~1.15 ms before the preamble, the transient never
  reaches a packet.

## Step 2–4: bench runs with the transmitter

Command: `cd host && .venv/bin/esp32sdr d8live --follow` (gain 40) and
`esp32sdr d8follow --seconds N [--kick S]`.

| Run | Duration | CRC-ok/s | Slots decoded | Losses | Re-acquire (after detection) | Stream loss |
|---|---|---|---|---|---|---|
| d8follow | 30 s | 105.7 | 97.9 % (3202/3270) | 0 | — | 0 |
| d8follow `--kick 12` | 60 s | 100.9 | 95.0 % (includes 4 forced outages) | 4 (forced) | 0.285, 0.114, 0.366, 0.186 s | 0 |
| **d8live --follow** | **159 s** | **108.0** | **97.7 % (17155/17557)** | **0** | — | **0** |

(`bench/hop-follow/d8live-follow-159s.log`.)

- First lock came 0.28–0.40 s after stream start (the acquisition channel comes round
  once per 422.5 ms).
- Fitted hop period 8.9893–8.9899 ms, so the cycle is 422.50 ms (not 8.994 ms nominal).
- 0 slot mismatches and 0 packet-counter mismatches: byte 4 rises by exactly 1 per hop.
- In `d8live`, a WebSocket client counted 108.5 CRC-ok packet messages/s over 145 s. The
  gap between updates was 9.0 ms median, 18 ms p99 and 62 ms max. Pipeline latency
  (packet end to publish) was a 15–16 ms median.
- `--kick` is a test aid: it shifts the firmware schedule by 4 ms with `HA`, so every
  retune lands mid-packet. Detection takes 47 hops (0.44 s), and re-acquiring takes up to
  one cycle (0.42 s), so a real outage costs ≤ ~0.9 s.
- Host CPU: decoding ~0.57 s per stream second, about 57 % of one core. `StandardDecoder`
  runs 5 filter cutoffs per segment. (Since cut to ~0.05 s: see *Decoder CPU* below.)

### Longer runs and other gains (2026-11-05, after the decoder CPU change)

| Run | Duration | CRC-ok/s | Slots decoded | Losses | Stream loss | Decode CPU |
|---|---|---|---|---|---|---|
| d8follow gain 40 | 630 s | 108.5 | 97.8 % (68 408/69 926) | 0 | 2248 samples (1 bad-CRC frame of 157.6 M) | 42.8 s (0.068 s/s) |
| d8follow gain 30 | 45 s | 107.2 | 98.0 % (4864/4964) | 0 | 0 | 2.79 s |
| d8follow gain 50 | 45 s | 107.5 | 97.8 % (4881/4990) | 0 | 0 | 2.76 s |
| d8follow `--gain hw` | 30 s | 0 | never locked | – | 0 | – |

(`bench/hop-follow/d8follow-630s-g40.log`.) In the 630 s run, 37 `HS` re-sends kept the lock. The fitted
period drifted from 8.9893 to 8.9887 ms (about −70 ppm between the tx and board clocks over 10 min).
Every slot except 33 ran at ≥ 99 %. Median latency was 10.8 ms. Hardware AGC never acquired, the same
failure as on one channel (it settles to a low gain index), so keep manual gain. Gains 30–50 behave the same.

### Slot 33 (channel 25, 2411.435 MHz): the transmitted signal is distorted

Slot 33 decodes 0–7 % at every setting tried. It is **not** the receiver, and the cause is most likely the
transmitter's synthesizer:

- **Same failure without hopping.** I recorded the channel alone with `bench/hop-follow/onechan.py`
  (1-bit, dec 64, 12–20 s). At mode 2, gain 40, it gave 0 CRC-valid packets. Mode 0 (LO at
  the channel) also gave 0. So did mode 2 with the stream centre moved ±50/±100 kHz (the decoder shifts
  back), and manual gain 20, 60 or 81 (60 gave 2 packets). In the same session, channel 23 (2410.835) and channel 40
  (2415.933) each decoded every packet. A 4-bit dec 256 recording (MLSE) gave the same result: channel 23 14/14,
  channel 25 0/10.
- **The burst is strong and clean in level, with nothing else on the channel.** In 4-bit, channel 25 bursts
  are as strong as channel 23 (mean |x|² 51 vs 47, 7.07 ms long). The samples outside the bursts are zero
  (no spur or interferer above 1 LSB).
- **The carrier frequency jumps during the packet.** `bench/hop-follow/resid.py` predicts each slot-33 packet
  from the CRC-valid slot-32 packet just before it (counter + 1, same channels). It then subtracts the ideal GFSK
  frequency of that packet from the discriminator output. Slot 19 leaves a flat residual of 0.7 kHz rms.
  Slot 33 leaves ±8–20 kHz steps that last 0.1–0.3 ms, scattered through the packet, at 7.3 kHz rms
  (`bench/hop-follow/slot33_resid.png`). The FSK deviation is ±31.7 kHz, so these steps flip bits
  and often break the preamble or sync word: only 15 of 70 slot-33 segments in a 30 s run even found sync.
  Faster carrier tracking (`track_bits` 4–16) and single-bit CRC repair recovered 0–1 of 70.
- **Why this channel.** The CC2500 sets the carrier with a fractional-N synthesizer from 26 MHz
  (FREQ = 0x5C7627, channel spacing 756 units of 26 MHz/2¹⁶). For channel 25 the ratio is
  92.749 93, which is 5 units (≈ 2 kHz) from exactly 3/4. Fractional synthesizers make strong near-carrier
  spurs and frequency wander when the fraction sits just next to a simple ratio. Channel 25 is the only one of the 47
  within 8 kHz of a ratio with denominator ≤ 8. The next closest is slot 30 (4/5, 8 kHz away), and it decodes at 99–100 %.
  This explanation is inferred: I did not measure the transmitter on a reference receiver.

There is no receive-side fix: the distortion is in the transmitted signal, and LO, IF, mode and gain
make no difference. The follower handles it already: one missed slot per cycle does not affect
lock (loss detection needs 47 missed hops), and it caps the slot rate at 46/47 = 97.9 %.

### Web page

`stats.follow` now also carries `slot_ok`, `slot_hops` (per hop slot) and `slot_mhz`. `host/web/d8live`
shows them as a 47-cell hit map in the follow bar (`src/hitmap.ts`; hover a cell for its slot, MHz and
count). The left-stick knob is centred in X for yaw 1500 µs: a headless render at (1500, 1627) puts it
exactly on the vertical centre line (`bench/hop-follow/stick_1500_1627.png`). In the old pad style, the
shadow at (+3, +4) px and the upper-left highlight can make the knob look offset.

## What is left

- Slot 33: the transmitter's signal on that channel is distorted (above); no receive-side fix.
- Decoder CPU: done (above). Confirmed live: 0.068 s per stream second over 630 s.
- Lock-loss detection is a fixed 47 hops. Coasting on the old schedule (fades) and
  acquiring on more than one slot would shorten outages.
- Not measured: runs longer than ~10 min.
