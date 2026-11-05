# ESP32 DevKit V1 profile

Profile `esp32-devkitv1`: classic ESP32 DevKit V1, CP2102, UART at 921600 baud
(CP2102 ceiling; 2 Mbaud silently fails and the board never answers). Receive only.

## Toolchain
ESP-IDF at commit `25fe69f946311abdaf9ad56591f25fedbc20ac98` (v6.1-dev), installed at `~/esp/esp-idf`.

## Build
Day to day:
```sh
. ~/esp/esp-idf/export.sh
idf.py -B build-esp32-devkitv1 -DIDF_TARGET=esp32 -DSDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32-devkitv1 build
idf.py -B build-esp32-devkitv1 -p /dev/cu.usbserial-0001 -b 921600 flash
```
Release artifacts:
```sh
python3 tools/build_firmware.py --profile esp32-devkitv1 --version dev --output /tmp/art
```
List profiles: `python3 tools/build_firmware.py --matrix`. The build tree is
`build-esp32-devkitv1/` in the repo root. (`build_firmware.py` passes
`-DESP_SDR_PROFILE=<id>` so the embedded version record names the profile, not just the chip.)

## Flash
```sh
. ~/esp/esp-idf/export.sh
python -m esptool --chip esp32 -p /dev/cu.usbserial-0001 -b 921600 --before default-reset --after hard-reset \
  write-flash --flash-mode dio --flash-size 2MB --flash-freq 40m \
  0x1000 build-esp32-devkitv1/bootloader/bootloader.bin \
  0x8000 build-esp32-devkitv1/partition_table/partition-table.bin \
  0x10000 build-esp32-devkitv1/esp_sdr.bin
```
Always pass `-b 921600`. Wait about 3 s after reset before talking to the board: the ROM and
bootloader log is printed at 115200 and looks like `0x00`/`0x80` noise at 921600. Then send
`RELEASE` and `SYNC <n>`, discard everything up to the echoed nonce, and continue.

## Host install
```sh
cd host && python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev,plot]
```

## Use
```sh
esp32sdr info
esp32sdr capture --freq 2437 --rate 40 --n 16380 -o ch6 --psd ch6.png   # SigMF + PSD
esp32sdr spectrum --freq 2437 --bins 1024 -o ch6.csv
esp32sdr stream --freq 2402 --dec 512 --bits 8 --seconds 60 -o ble    # continuous, ~31 kHz wide
esp32sdr bridge --listen 127.0.0.1:1234                              # rtl_tcp for gqrx
esp32sdr sdrpp                                                       # SDR++ live view
esp32sdr d8live --center 2421.032 --gain 40 --open                   # FrSky D8 live page, one channel
esp32sdr d8live --follow --gain 40 --open                            # same, all 47 hop channels (~108 pkt/s)
esp32sdr d8follow --seconds 60                                       # hop follow, console stats only
```
`--port` defaults to `/dev/cu.usbserial-0001`. The d8live page needs a one-time
`cd host/web/d8live && npm install && npm run build`. Hop following needs this firmware
(`HOPTAB`) and a manual gain. See `bench-results.md`, `live-view.md` and `hop-follow.md`.

## Check the link
Open `/dev/cu.usbserial-0001` at 921600 and send `VERSION?`, `INFO`, `TRANSPORT?`;
expect `TRANSPORT UART 921600`.

## Bench recovery
- Reset through RTS (pulse RTS low then high, DTR high); the board may be held in reset
  by a host that left RTS asserted.
- If the board never answers, check the baud: 2 Mbaud is a dead-board trap on the CP2102.
- Re-flash at `-b 921600` if unsure of the running firmware.
