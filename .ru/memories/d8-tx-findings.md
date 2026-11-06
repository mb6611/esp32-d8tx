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

**How to apply:** start new TX work from these numbers instead of re-deriving them, and recheck the carrier wander if decoding gets marginal on other channels.
