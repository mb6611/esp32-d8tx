# tools/txeng

`txeng` is the ESP32 firmware I used to drive the playback engine at `0x60033d98` and read its registers (experiments [01](../../experiments/01-playback-engine-check/README.md) and [02](../../experiments/02-register-map/README.md)). It is a small ESP-IDF app that takes line commands over the UART at 921600 baud, fills the 64 KiB sample window, keys the transmitter, starts the engine for a given count, and prints one `E,...` line with the cycle counts and register snapshots taken around the run. Replies end in `OK` or `ERR`.

- `main/txeng.c`, `CMakeLists.txt`, `sdkconfig.defaults`: the firmware.
- `dev.py`: the host side, a `Dev` class that resets the board through RTS, sends a command and collects the reply, and raises `Hang` when the chip reboots in the middle of a command (the firmware arms the RTC watchdog at about 3 s, so a bus-hanging register write reboots the chip instead of wedging it).
- `run.py`, `iq.py`: the script and helpers that produced the engine runs A to E (`experiments/02-register-map/data/engine-runs/results.csv`). They need numpy.

## Build and flash

I built it with ESP-IDF at commit `25fe69f946311abdaf9ad56591f25fedbc20ac98` (v6.1-dev-6376) and xtensa-esp-elf esp-16.1.0_20260609, for an ESP32 DevKit V1 on `/dev/cu.usbserial-0001`. Its CP2102 USB-UART tops out at 921600 baud, so flash at that rate:

```sh
. ~/esp/esp-idf/export.sh
cd tools/txeng
idf.py build
idf.py -p /dev/cu.usbserial-0001 -b 921600 flash
```

The host side needs Python with pyserial (and numpy for `run.py`). The experiment scripts import `dev.py` from here by a path relative to the script.

The register census that the register map also cites is under `experiments/02-register-map/data/register-census/`, with its source in `census/`.
