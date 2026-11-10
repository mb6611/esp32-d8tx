# 01: Does the playback engine radiate?

I had found a block in the ESP32 at `0x60033d98` that behaves like an I/Q playback engine (the engine runs are in [02's data](../02-register-map/data/engine-runs/results.csv)): given a count, it steps through the same 64 KiB sample window the receive side captures into, at 80 or 40 MS/s, and then reports done. If that engine actually sent its samples to the antenna, transmitting D8 would be simple: build the packet as I/Q samples and play them. So the first question here was whether the samples go out on the air, or only the act of keying the transmitter does.

The receiver was the drone's flight controller. Its CC2500 ran a receive-only diagnostic firmware ([tools/cc2500-rxdiag](../../tools/cc2500-rxdiag/)) in `rxdiag events` mode, which logs every short burst of energy with its duration and peak RSSI (the chip's raw, uncalibrated signal-strength reading). I set it to 2412 MHz with an 812 kHz bandwidth, so it saw ±406 kHz around the ESP32's carrier. A threshold sweep came first: at AGC 251/64 it reported only 3 bursts per second of ambient noise and was too insensitive, so I used 203/66, which gave 6 to 11 ambient bursts per second.

On the ESP32 I ran the `txeng` firmware ([tools/txeng](../../tools/txeng/README.md)), key mode `K 0`, power code 127. A script sent slots in a seeded random order, at least 0.35 s apart, under several conditions: the ESP32's built-in test tone (a known radiator, the positive control), a sample pattern whose line should sit at ±1.25 MHz, a constant DC sample (I = 200), all-zero samples, the engine run without keying the transmitter, and idle. For each slot I counted a hit if the receiver logged a burst between 1.5 and 4.5 ms after the command, a window I chose from a pilot run where the lag was about 2 to 3 ms.

The keyed slots were all seen. In session A (15,360 samples, 192 µs of engine time) the tone, the pattern and the zero samples each hit 20 of 20 slots, the unkeyed engine 0 of 20, and idle 1 of 20. In session B (12,288 samples, 154 µs) the DC and zero samples each hit 20 of 20 and idle 0 of 20. But the pattern, DC and zero slots looked the same. Their median peak RSSI was −5 raw for the pattern and −6 for zero in A, −2 for DC and −1 for zero in B, against +20 for the tone, so the samples changed the reading by about one raw step at most. The burst length followed the engine length (median 247 µs in A, 203 µs in B), but the keyed time shrank by the same amount, so that doesn't separate "engine running" from "transmitter keyed".

So the receiver saw the transmitter being keyed, and nothing that depended on the samples. That isn't evidence that the samples don't go out, because this test could hardly have seen them. The pattern's line at ±1.25 MHz was outside the ±406 kHz the receiver looked at. A DC sample may be cancelled by the transmitter's own carrier leakage or DC removal. And I never verified what format the engine plays (I/Q order, width, scaling). With 20 slots, an uncalibrated RSSI and no statistical test, the similar medians are an observation, not an upper bound.

There was also a bench problem. Three keyed bursts ran longer than the 444 µs limit I had set for this test: 483, 445 and 448 µs, each the first keyed slot after the ESP32 booted. I kept going in session A after the 483 µs one, and B overran too, so I stopped keying after B.

I then tried three ways to put the sample-dependent signal where the receiver could see it, each with its analysis rules written and hashed before keying. With the receiver at 2413.25 MHz and 203 kHz bandwidth, on the pattern's line, there were no bursts at all, not even from the keyed zero slots, so there was no positive control. With a pattern at +156.25 kHz and the receiver at 2412.156 and 2411.844 MHz, every condition was 0 of 8; the control at 2412.000 MHz passed (tone 5 of 5, keyed zero 5 of 5), but at the offsets even keyed zero was invisible. Finally I compared DC against zero samples at 2412.000 MHz with the engine's memory bank set to the lower or upper half. With the lower bank the control passed and DC and zero both hit 8 of 8 with median peak −1 raw (Mann-Whitney p = 0.851). With the upper bank the tone hit only 6 of 8, below the 7 of 8 I had required, so that run doesn't count.

At that point I reviewed whether one more run could answer the question (`data/NO_RERUN_NOTE.md`). It couldn't: the only known radiator was the tone at the carrier itself, outside any offset slice, so a null would again mean nothing. It would take an independent source at the slice frequency, or a receiver wide enough to see ±1.25 MHz lines. I stopped keying here. The open question about the engine went into a register map ([02](../02-register-map/README.md)), and the transmit work moved to keying the test tone directly ([03](../03-tone-first-attempt/README.md)), which is the path that later sent a D8 packet.

---

## Numbers

| What | Value | Where |
|---|---|---|
| Keyed slots with a burst, session A (tone, pattern, zero) | 20 / 20 each | `data/tight_window_output.txt` |
| Keyed slots with a burst, session B (DC, zero) | 20 / 20 each | `data/tight_window_output.txt` |
| Unkeyed engine runs with a burst | 0 / 20 | `data/tight_window_output.txt` |
| Median peak RSSI (raw): pattern, zero (A); DC, zero (B); tone (A) | −5, −6; −2, −1; +20 | `data/README.md` |
| Keyed bursts over the 444 µs limit | 3 (483, 445, 448 µs) | `data/README.md` |
| Bank check, lower bank: DC vs zero | 8/8 vs 8/8, p = 0.851 | `data/bank-check/README.md` |

## Files

- `data/`: everything as recorded. `data/README.md` is the original write-up of the main sessions; `sessions/` holds the pilots and sessions A and B, `sweep2412/` the threshold sweep, and `inband/`, `intended/` and `bank-check/` the three follow-up runs, each with its own README. `NO_RERUN_NOTE.md` is the review that ended the experiment.
- `scripts/`: `pbcheck.py` drove the hardware; `analyze.py` and `tight_window.py` turn `data/sessions/` into the summaries; `guard.py` and `test_guard.py` are its safety checks; `prereg.py` files fixed each analysis before the run.

## How to re-run

Offline, from `experiments/01-playback-engine-check/data`:

```
python3 ../scripts/tight_window.py sessions/pilot2-km0 sessions/A-km0-p127 sessions/B-km0-p127-dc   # = tight_window_output.txt
python3 ../scripts/analyze.py sessions/A-km0-p127 --json /tmp/A.json                               # = A.json (same for B)
python3 ../scripts/intended/fillcheck.py                                                           # needs numpy
python3 ../scripts/test_guard.py                                                                   # needs pyserial
```

`pbcheck.py` (hardware) needs the ESP32 and the drone, and imports the `txeng` host code from [tools/txeng](../../tools/txeng/README.md). `bank-check/offline_check.py` reads `tools/txeng/main/txeng.c`, the ESP-IDF header and `librftest.a` from `~/esp/esp-idf`, and `objdump` from `~/.espressif`; it also compares against a capture-side note in the esp32-d8rx repo and skips that one check if the note is not there.

## Ran

2026-11-05, from 19:37 EST (the first `utc=` stamp in the threshold sweep, 2026-11-06T00:37Z). The last recorded time is the bank-check pre-registration at 22:29 EST (03:29Z); its two keyed sessions ran after that and carry no timestamp. Committed later in one bulk add: 8dde1a9 (2026-11-06 13:38).

Previous: [esp32-d8rx experiments](https://github.com/mb6611/esp32-d8rx/tree/main/experiments) (the receive side came first) · Next: [02-register-map](../02-register-map/README.md) · [All experiments](../README.md)
