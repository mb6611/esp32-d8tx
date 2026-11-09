---
name: d8-tx-findings
description: Read before extending ESP32 D8 transmission (hopping, more packets, other channels) or measuring ESP32 tones with the Tinyhawk CC2500; measured facts from the first-packet milestone, Nov 2026.
load: description
---
Measured on 2026-11-06 (evidence under `bench/d8-tx/results/{tone,packet}/`):

- ESP32 tone setting `f` moves the carrier ~**39.06 kHz per unit** (40 MHz/1024) from the Wi-Fi ch1 carrier at 2412.000 MHz; f=0 is the bare carrier. ±16 measured ≈ +650/−600 kHz; fine steps ±1/±2/±4 hit their predicted frequencies (the ROM puts f&3 in fine bits).
- Hard 2-FSK at f=±1 (no Gaussian shaping, ~23% over stock D8 deviation) at 31,044 baud, cycle-counted on the ESP32, was decoded by the CC2500 with valid hardware CRC: 7/10 packets byte-exact, power code 127.
- Carrier lands ±~10 kHz differently per keying; cause unresolved. It did not stop packet decode.
- CC2500 FREQEST is useless outside its filter and saturates on ambient 2.4 GHz traffic at wide bandwidth. To locate a tone, retune the receiver and look for high RSSI + stable FREQEST; use bw 102 kHz, agc 203/66. agc 251/64 is too insensitive; very low agc2 trips on ambient.
- The Tinyhawk's stock config has `frsky_spi_offset = -32` (≈ −51 kHz) to match the E8. The diagnostic doesn't apply it, so receive the E8 at its measured frequency (2421.032 MHz for nominal 2421.096).
- Noise produces short CRC-failed fragments in `rxdiag pkt` even with all sources off. Count only `crc_ok=1` records.
- Betaflight CLI enters DFU with `bl`, not `dfu`.
- Fixed-channel packet loss (2026-11-06, `bench/d8-tx/results/packet/{reliability,freqest}/`): the ESP32 reached ~95% CRC-valid reception on the CC2500 rxdiag (123/130 attributable), and the stock E8 on the same receiver reached ~93% (175 of ~189 expected; it revisits one channel every 422.7 ms). The owner accepted this as receiver/bench loss, cause unknown, and moved on. Per-packet FREQEST clamps at ±33.3 kHz and scatters ~15 kHz even for the E8, so it cannot resolve small carrier offsets.

**How to apply:** start new TX work from these numbers instead of re-deriving them, and recheck the carrier wander if decoding gets marginal on other channels.

Telemetry listen prep (2026-11-07, no battery; `bench/d8-tx/host/tlm_listen.py`, firmware `TLM`/`TCAP`, results `bench/d8-tx/results/telemetry/`):
- In Betaflight 4.2 `cc2500_frsky_d.c`, `nextChannel(1)` runs before `STATE_TELEMETRY`, so the reply goes out on the **next** hop channel, not the trigger channel (the write-up §8 says "same channel"). Check this before assuming either.
- After keying a packet, the ESP32 RX hears the 2440 MHz crystal harmonic again within the first ms (unkey→capture start 0.21–0.31 ms, mostly the retune). So the RX does recover after TX. This is different from the stage-2 "deaf during K 0" result.
- The single-core 16 MS/s ring capture (`tlm_cap.c`) only keeps up when built at -O2. The project default is -Og, which lost 65% of pairs.

Telemetry catch rate (2026-11-07, `results/telemetry/SUMMARY.md`): any multi-slot TX pause (e.g. the old blocking UART capture dump, ~24 slots) puts Betaflight into RX failsafe and loses hop phase; use `TLM ... stream=1` (background int8 shipping) so only the reply slot is skipped. The drone's FEATURE_TELEMETRY is off (MSP feature mask 0x32450000), so hub byte count is always 0 and no ACC/hub data exists without an owner-approved config change. The remaining ~13% misses have no reply in the capture at all: a known-bits template correlation is ≤0.10 vs ≥0.75 for replies. Gain 40, the window and the decoder margins are fine, and a better host decoder recovers only 1 in 417 (offline analysis, `results/telemetry/MISSES.md`, `host/tlm_misses.py`). (Superseded 2026-11-08, below: those misses were the drone losing our packets because of the carrier offset.)

Telemetry (2026-11-07): the owner approved turning on `feature TELEMETRY` on the Tinyhawk; it was left on (revert: `feature -TELEMETRY`, `save`). Hub frames now arrive in D8 replies. Betaflight 4.2 hub ACC is truncated to whole g, so a level drone reads ACC Z = 0, not 1 g. That is not a decoder bug. Details are in bench/d8-tx/results/telemetry/SUMMARY.md.

Carrier offset (2026-11-08, SUMMARY.md "Why the drone did not reply"): at FOFS -50 kHz the Tinyhawk lost ~15-20% of our packets, trigger and control packets alike. A ch8 marker read back over MSP_RC showed the missed triggers were never decoded (1 of 88), and slot timing was not a factor. Our carrier sat ~35 kHz above the drone's synthesizer. A FOFS sweep gives a plateau from -65 to -80 kHz: **-75 kHz → 97.8-99.3% of triggers answered**, vs 82% at -50 back to back. Re-check with a short sweep if catch rates drop, because the drone's frequency drifts a few kHz between sessions. The Mac sleeps on battery mid-run (pmset log shows Maintenance Sleep), so keep it awake for bench runs (`caffeinate -dimsu`).

OTA bind (2026-11-09, `bench/d8-tx/results/bind/SUMMARY.md`): the Tinyhawk is now bound to the DevKit's own identity (txid 6ff3, start 205, step 254, receiver offset 3), not the E8 one. After binding, FOFS 0 is the best offset (94.9% catch at power 127 vs 72.9% at −75 kHz); the −75 kHz workaround only applied to the E8 binding. Bind tunes the receiver to whatever FOFS was active during BIND, so links must use the same FOFS. E8 restore commands are in that SUMMARY.
