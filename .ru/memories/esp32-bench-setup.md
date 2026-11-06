---
name: esp32-bench-setup
description: Read before building, flashing or talking to the ESP32 DevKit V1 on the bench (esp-sdr, stage0/1/2 firmware); toolchain pins, serial port and baud limits, venv, reset and hang recovery as of Nov 2026.
load: description
---
The bench setup that stages 0–2 share. Exact commands live in `stage0/README.md`
("Install", "Build and flash"), `stage1/README.md` ("Commands") and `stage2/README.md`
("Files"); run those rather than improvising.

- Board: ESP32 DevKit V1 (ESP32-D0WD-V3 rev 3.0, 40 MHz XTAL, 4 MB flash) on
  `/dev/cu.usbserial-0001`. Its USB-UART is an original CP2102: **921600 is the ceiling**,
  2 Mbaud silently fails (board never answers). Pass `-b 921600` to `idf.py flash`.
- `esptool read-flash` (full-flash backup) failed at 921600 and 460800 with "Invalid head of packet"; 230400
  worked (2 MB in ~95 s, Nov 2026). Writing at 921600 is fine.
- Toolchain pins: ESP-IDF at `~/esp/esp-idf` @ `25fe69f946311abdaf9ad56591f25fedbc20ac98`
  (`v6.1-dev-6376`, the commit esp-sdr's `firmware-targets.json` pins for profile `esp32`),
  xtensa-esp-elf esp-16.1.0_20260609, esp-sdr at `vendor/esp-sdr` @ `9b61e74`. Always
  `. ~/esp/esp-idf/export.sh` first.
- Host Python: one shared venv, `stage0/.venv` (numpy, pyserial). Stage 1 and 2 scripts are run
  as `../stage0/.venv/bin/python <script>`.
- esp-sdr build: no source patches, one config override (`stage0/sdkconfig.uart921600`) applied
  through `SDKCONFIG_DEFAULTS` into a separate build dir `build-esp32-921k`. `build-esp32/` is
  the stock 2 Mbaud build and is unusable on this board.
- Console baud differs by stage: stage 1 census talks at 115200 (default console); stage 2 txeng
  at 921600 (needs `CONFIG_ESP_CONSOLE_UART_CUSTOM`, otherwise
  `CONFIG_ESP_CONSOLE_UART_BAUDRATE` is ignored). Host scripts default to the right one.
- Reset and recovery: the host scripts reset the board through RTS. Both stage firmwares arm the
  RTC WDT at about 3 s with reset-system, so a bus-hanging register write reboots the chip
  instead of wedging it. Stage 1 resumes after a hang from an RTC-memory cursor; stage 2's host
  treats an unexpected `I,boot` line as a HANG for that command. Writing `0x60033d00..d20` hangs
  the chip (stage 2 firmware refuses those addresses).
- Stage apps are unicore like esp-sdr and reserve `0x3ffe8000..0x3fff8000` (the 64 KiB sample
  window).

**Why:** the 2 Mbaud dead-board and the console-baud config trap each cost a debugging session.
**How to apply:** check the pins and paths still exist before relying on them; the board or venv
may have been moved.
