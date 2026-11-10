# firmware

ESP-IDF firmware for the ESP32 DevKit V1 (classic ESP32). It keys an FSK tone through the PHY calibration path to transmit FrSky D8 packets, hops 47 channels on a 8.994 ms slot, receives the drone's telemetry replies, and takes commands over USB serial (`LINK`, `S`, `BIND`, `ID`, `INFO`, `STAT`, ...). Protocol: [protocol/PROTOCOL.md](../protocol/PROTOCOL.md). How the transmit path works: [writeup](../docs/lab-log/tx.md).

## Build and test

```sh
make -C firmware test      # offline host tests (plain cc, no ESP-IDF)
make -C firmware build     # idf.py build (needs ESP-IDF; IDF_EXPORT=~/esp/esp-idf/export.sh)
make -C firmware web       # build + copy the images into apps/web/public/firmware
make -C firmware version   # version of the current sources
```

See [how-to/rebuild-firmware-bundle.md](../docs/how-to/rebuild-firmware-bundle.md). Flash with the app, or `idf.py flash`.

## Key files

- `main/d8tone.c`: tone keying, bit timing, link loop, hopping.
- `main/packet.c`: D8 packet and CRC builder.
- `main/cmd_parse.c`: serial command parser (release and `CONFIG_D8_BENCH` command sets).
- `main/tlm_cap.c`: telemetry capture on the DevKit.
- `test/`: host tests, including `test_vectors.c` against `protocol/vectors`.
- `tools/web_bundle.mjs`, `tools/fw_version.mjs`: bundle and version for the app's flasher.

Identity (`txid`, hop table) is random per DevKit and kept in NVS; flashing through the app never erases it.
