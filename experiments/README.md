# Experiments

These are the measurements behind the project, in the order I ran them. They build on the receive side, which came first: before I tried to transmit, I got the ESP32 to receive and decode FrSky D8, and those experiments are in [esp32-d8rx](https://github.com/mb6611/esp32-d8rx/tree/main/experiments). Here the question turns around: can a classic ESP32, using only its own Wi-Fi radio, send D8 that a real receiver accepts, and then fly a stock Betaflight drone and hear it talk back.

The receiver in most of these is the drone itself, a Tinyhawk with a MATEKF411RX flight controller and a CC2500 radio. In 01 to 07 the CC2500 ran a receive-only diagnostic firmware that reports what it hears; from 08 on it ran Betaflight.

## 01: [Does the playback engine radiate?](01-playback-engine-check/README.md)

2026-11-05, 19:37 to 22:29. I had found a block in the ESP32 that steps through a sample buffer like an I/Q playback engine, and wanted to know if its samples reach the antenna. The CC2500 saw every keyed slot (20 of 20 for each sample type, 0 of 20 for the engine run unkeyed), but the samples changed the peak reading by about one raw step at most, against +20 for the test tone. So the transmitter keyed, and nothing showed that the samples went out with it, partly because the test could hardly have seen them.

## 02: [Register map of the ESP32 radio](02-register-map/README.md)

2026-11-06, finished by 13:38 (the hardware reads are undated). Before more RF tests I mapped what is known about the classic ESP32's transmit path, from disassembly of the ROM and vendor libraries, the ESP32-S3's documented path and a few reads on my board, keeping measured, mapped and guessed rows apart. No classic vendor binary uses the playback engine, and the two blockers I could name (a tone generator left on, the interpolator held down) weren't set during keying. What decides whether the samples reach the antenna stayed unknown, so I moved to the built-in test tone.

## 03: [First try at a keyed tone](03-tone-first-attempt/README.md)

2026-11-06, 00:37 to 00:53. I keyed the ESP32's built-in test tone at 2412 MHz, at the centre and ±16 steps, with the CC2500 sensing for a carrier. All 12 keyed commands ran, and the receiver sensed a carrier in 0 of them, while the real E8 control showed up. With no known signal at 2412 MHz, I couldn't trust that null.

## 04: [Finding the tone](04-tone-scan/README.md)

2026-11-06, 12:20 to 12:46. I checked the detector and then scanned for the tone. With the old 812 kHz filter the carrier sense fired on plain noise in 30 of 30 windows, and with a 102 kHz filter in 2 of 30. With that fixed, the tone sat at 2412.000 MHz and one step moved it about 39 kHz, so the ±16 tones of 03 had been about ±625 kHz away, outside the receiver's passband.

## 05: [The first packet](05-first-packet/README.md)

2026-11-06, 12:59 to 13:01. One tone step is close to the ±31.7 kHz deviation of D8, so I keyed a 26-byte D8 packet as 2-FSK at about 31,043 baud and asked whether a real CC2500 accepts it. Of 10 packets sent, 7 arrived byte for byte with a valid CRC; with no transmitter on, the receiver produced no CRC-valid record.

## 06: [Fixed-channel reliability](06-fixed-channel-reliability/README.md)

2026-11-06, 14:29 to 15:32. I sent batches of ten packets on one channel and compared with the real E8 on the same receiver. The ESP32 got 132 of 140 packets through (94%), the E8 175 of about 189 (93%), with overlapping 95% intervals and not one CRC-invalid packet. Along the way the "right bytes, CRC flag 0" records of 05 turned out to be my receiver firmware cutting packets after 500 µs.

## 07: [Hopping](07-hopping/README.md)

2026-11-06, about 15:40 to 16:00. The ESP32 retuned to a new channel every 8.994 ms slot, through the E8's 47-channel hop table, with each retune taking at most 0.39 ms. It got 543 of 556 and 921 of 940 slots through (97.7% and 98.0%), against the E8's 96.8%, with every channel decoding.

## 08: [First flight, posing as the E8](08-first-flight-cloned-e8/README.md)

2026-11-06, 16:14 to 17:02. Using the E8's transmitter ID and hop table, plus a −63 kHz carrier offset, I pointed the ESP32 at stock Betaflight 4.2.11. Betaflight read the sticks exactly as sent, armed only when allowed, and a scripted one-second full-throttle pulse lifted the drone off the bench. When the host program died, the ESP32 stopped after 0.30 s and Betaflight disarmed 1.25 s after the host died.

## 09: [Hearing the drone talk back](09-telemetry/README.md)

2026-11-07 20:40 to 11-08 00:26. After a trigger packet the ESP32 switched to receive and captured Betaflight's telemetry reply on the next hop channel. The first run caught 26 of 46 replies; streaming the capture between packets instead of pausing the link took it to 87%, and moving the carrier offset from −50 to −75 kHz to 97.8 to 100%. Stock Betaflight's hub data turned out to be coarse, acceleration in whole g.

## 10: [Patching Betaflight for real numbers](10-hub-patch/README.md)

2026-11-08, about 10:33 to 12:55. A patch to Betaflight's hub telemetry added acceleration in milli-g, an arm and mode STATUS word, gyro and attitude; a second patch added this drone's ICM20689 gyro driver to the board target. Over the radio 207 of 208 triggers were answered, the level drone read +1004.5 milli-g on Z, and the armed bit arrived 0.63 s after the switch, against 0.15 s over USB.

## 11: [Telemetry inside the app's library](11-telemetry-stack/README.md)

2026-11-08, 10:39 to 12:16. Telemetry inside the Python library and backend answered 1387 of 1395 triggers (99.4%) over 10 minutes, with the stick sender at 111 Hz and none skipped. In that run the hub data stopped after 12.9 s; the cause was a signed 32-bit time compare in Betaflight that skips every hub cycle when the drone last sent hub data 36 to 72 minutes earlier, and a model of it matched the log reply by reply.

## 12: [Blackbox over USB](12-blackbox-usb/README.md)

2026-11-08, 12:54 to 13:24. I streamed Betaflight's blackbox log over the shared USB port, since the board has no flash or SD card. One session decoded to 13,655 frames at 954 Hz after I rebuilt its lost header, but each arm and disarm makes Betaflight reinitialise USB, the Mac doesn't re-enumerate, and the reset workaround once hung the flight controller. Still open.

## 13: [Fast attitude over the radio](13-fast-attitude-telemetry/README.md)

2026-11-08, about 13:34 to 14:15. Patch 0003 puts a 10-byte attitude and gyro block in two of every three replies, and smaller int4 captures let the ESP32 trigger every 12 slots. Replies went from 2.3 to 8.5 a second, and attitude from one update every 7 s to 5.7 a second, enough for a live 3D view.

## 14: [Checking the real app](14-app-validation/README.md)

2026-11-09, 13:21 to 13:35 and 15:45 to 15:47. The app ran the link on the hardware with no backend. A 10-minute run kept every gap between stick updates under 25 ms and decoded 96.0% of telemetry, and arming, the throttle cap, disarming and a simulated port loss all behaved safely. A later 2-minute run with the ESP32's own identity got 73.2%, and I haven't found why.

## 15: [Binding over the air](15-ota-bind/README.md)

2026-11-09, 14:10 to 14:22. The ESP32 drew a random identity and bound the drone to it on the first try, in about 4 s. The drone's receiver corrected its own offset by +36 steps (about +57 kHz) while binding, so FOFS 0 became right: 94.9% of telemetry triggers answered, against 72.9% at the old −75 kHz.

Overlaps: 02 ran alongside 03 to 08. 10, 11 and 12 ran in parallel on 2026-11-08. 14 straddles 15. Times are EST, from timestamps in the data and from git; each README says how its times were found.

---

## What is in each folder

- `README.md`: the story of the experiment, its figures, then a reference footer with the numbers, files, how to re-run it and when it ran.
- `data/`: raw data as recorded, never edited. Original notes from the time (`NOTE.md`, `SUMMARY.md`, `NOTES.md`) are kept there unchanged, so some paths inside them are the old ones (`bench/d8-tx/results/...`).
- `scripts/`: the scripts that recorded the data or turn it into figures and numbers.
- `figures/`: generated figures and other derived outputs.

Shared tools used by several experiments are in [`tools/`](../tools/): the bench host library and its tests (`tools/d8-tx-host`), the CC2500 receive-only diagnostic (`tools/cc2500-rxdiag`), the Betaflight patches (`tools/betaflight-patch`) and the blackbox tools (`tools/blackbox`). The original writeup is archived, unedited, in [`docs/lab-log/`](../docs/lab-log/tx.md).

## Re-running the offline checks

Run these from the repo root (Python 3 with numpy and matplotlib; pyserial and pytest for the tests):

```
python3 experiments/05-first-packet/scripts/plot_tx.py
python3 experiments/06-fixed-channel-reliability/scripts/plot_reliability.py
python3 experiments/07-hopping/scripts/plot_hop.py
python3 experiments/08-first-flight-cloned-e8/scripts/plot_latency.py
python3 experiments/12-blackbox-usb/scripts/plot_telemetry.py
python3 -m unittest discover -s tools/d8-tx-host/tests
```

Set `FIGURES_OUT=/tmp/figs` to write the figures to a scratch folder instead of `figures/`. Each experiment's README lists its other offline scripts. Everything else in `scripts/` drives hardware (ESP32 and drone) and was not re-run.

## Data size

All data is committed. No single file is over 20 MB, so nothing is stored as a release asset.
