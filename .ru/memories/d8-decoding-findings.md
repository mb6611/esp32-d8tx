---
name: d8-decoding-findings
description: Read before recording or decoding FrSky D8 packets with the DevKit V1 SDR (E8 true frequency, stream format, gain, decoder in host/esp32sdr/d8.py), as of Nov 2026.
load: description
---
What worked for decoding the E8 transmitter's D8 packets (Nov 2026, `host/esp32sdr/d8.py`, CLI `python -m esp32sdr.d8_cli`; full write-up in `docs/devkitv1/bench/d8/centred-m2.md`):

- The E8's table channel 2421.096 MHz (pos1) is really at **2421.032 MHz** (−64 kHz, ~−26 ppm). This was measured on 2026-11-05 from CAP16 bursts at 16 MS/s, at LO 2420 and at LO 2417.140, and confirmed by decoding. Expect the other table channels to be off by about the same ppm.
- A second tx-66,178 burst seen in the slot before the real one, at an apparent ~2421.13–2421.21, is a spur: its frequency moves with the LO. Do not centre on it. The earlier "E8 at 2421.140" claim came from it.
- Best working setup: 1-bit, dec 64, `--mode 2` centred at 2421.032, with **manual gain**. `docs/devkitv1/bench/d8/rec_centred.py BASE 2421.032 40 20` gave 47/47 CRC-valid packets in 20 s.
- Hardware AGC can lock to a low gain index (16 seen), which leaves almost nothing to decode (1 in 20 s). Gain indices 30–81 all worked.
- With 1-bit samples the channel filter must be narrow, about ±35–50 kHz. ±75 kHz loses a third of the packets. `StandardDecoder` now runs several cutoffs and merges the results per burst.
- dec 256 (62.5 kS/s) aliases the ±31.7 kHz tones onto each other. Only the MLSE path decodes it, and only partly.
- The E8 sends byte 3 = 0x00, and byte 4 is the packet counter (+47 per hop cycle of 422.5 ms).

**How to apply:** centre at the measured frequency, not the nominal one. Set a manual gain. Check the decoder with `host/tests/test_d8.py`.
