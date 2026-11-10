# Regulatory status

Educational and research use. This is how the project reads under US FCC rules (47 CFR Part 15); it is not legal advice, and **you are responsible for following the regulations where you are** before building or using the transmit code.

- **Home-built device (§15.23).** The ESP32 module's FCC grant covers Wi-Fi and Bluetooth only, so this firmware makes it a home-built intentional radiator: one unit, personal use, not marketed or sold (no boards, kits or pre-flashed units). §15.23 asks for a good-faith engineering effort to meet Part 15 limits, not laboratory measurement.
- **All transmit modes are held to §15.249**, the rule the FrSky-compatible EMAX E8 it replaces is certified under (FCC ID [2AL7Y-EMAXE8](https://fccid.io/2AL7Y-EMAXE8)): 2400 to 2483.5 MHz, 50 mV/m (94 dBµV/m) average and 114 dBµV/m peak at 3 m, i.e. about -1.25 dBm average and +19 dBm peak EIRP. This covers LINK (hopping), BIND (one channel, at most 30 s) and the bench modes alike.
- **The ESP32's output is estimated, not measured**, by comparison with the E8 (below): about -25 dBm peak EIRP at full power, at least 16 dB under the limit in every run.
- **Harmonics and spurious emissions of the ESP32 were not measured**; the design relies on the module's certified RF output filter.
- **Tests were radiated, indoors, at bench range**, with no conducted or lab measurements.
- **Release build.** The single-channel and tone bench modes (TONE, ALT, RETUNE, PKT, HOP with `n_slots`, TCAP keying) compile only with `CONFIG_D8_BENCH=y` (default `n`), so a release build exposes LINK, BIND and housekeeping commands. `CONFIG_D8_PWR_MAX` caps the power setting, a raw PBUS code, not dBm; it is not calibrated.

## EIRP estimate from CC2500 RSSI

The E8's certification test report (Shenzhen Tongzhou Testing, report TZ210902562-E, 2021, [on fccid.io](https://fccid.io/2AL7Y-EMAXE8/Test-Report/Test-Report-DXX-5536602), page 24) measured its D8 mode at 3 m: at most 87.15 dBµV/m average and 96.32 dBµV/m peak, which is -8.05 dBm average and about +1.1 dBm peak EIRP (internal antenna, 3 dBi max). Its harmonics were at least 8 dB under the limit.

The same CC2500 receiver (the MATEK F411RX running `rxdiag`) reported the signal strength of the real E8 and of the ESP32, from CRC-valid packets in the saved logs (RSSI conversion in [`protocol/PROTOCOL.md`](protocol/PROTOCOL.md)):

| Source | Mode, power | Mean RSSI | Log (under `experiments/`) |
|---|---|---|---|
| Real E8 | hopping, 2133 packets | -32.3 dBm | `07-hopping/data/e8_control/e8_hop_20s.txt` |
| ESP32 | hopping, `HOP 556 127` | -58.7 dBm (two runs, 510 and 472 packets) | `08-first-flight-cloned-e8/data/offset_tune/runA.txt`, `runB.txt` |
| Real E8 | fixed 2421.032 MHz | -32.8 to -36.2 dBm (three controls) | `05-first-packet/data/control_e8_2421032.txt`, `06-fixed-channel-reliability/data/reliability/control_e8*.txt` |
| ESP32 | fixed 2412.000 MHz, `PKT ... 127` | about -59.5 dBm in 12 batches; -54 in three; -65.9 in the first (7 packets) | `06-fixed-channel-reliability/data/reliability/batch*_stm.txt`, `06-fixed-channel-reliability/data/freqest/batch*_stm.txt`, `05-first-packet/data/batch1_2412000_stm.txt` |

The ESP32 at power 127, the maximum, arrives about **26 dB below** the E8 (18 to 33 dB across all runs). The CC2500 reads power while a packet is on air, so the comparison is against the E8's peak: the ESP32 is about **-25 dBm peak EIRP**, -32 to -17 dBm across runs. Even the highest run is about 16 dB under the -1.25 dBm average limit (a continuous tone's average equals its peak) and far under the peak limit. The estimate is not a measurement: distance, orientation and antennas were not controlled, the RSSI is uncalibrated, the ESP32 level moved about 5 dB between sessions, and our E8 unit may not radiate exactly what the tested sample did. The margin is larger than these uncertainties are likely to be.

The same section, with the surrounding measurements, is in the [writeup](docs/lab-log/tx.md#regulatory-status).
