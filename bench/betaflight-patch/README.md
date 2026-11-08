# Patched Betaflight 4.2.11 (MATEKF411RX): richer FrSky hub telemetry

Patch 0001 (`patches/0001-frsky-hub-telemetry.patch`) changes only `src/main/telemetry/frsky_hub.c`: true milli-g ACC (stock
truncates to whole g), STATUS 0x46, ARMING_DISABLE 0x47, gyro 0x40-0x42, attitude 0x43-0x45. Encoding, rates and
byte budget: `d8tx/PROTOCOL.md` "Patched Betaflight hub fields". Patch 0002 (`0002-matekf411rx-icm20689.patch`, ICM20689 gyro support) also changes `target/MATEKF411RX/target.h` and `target.mk`. Everything else is stock.

## Build
`./build.sh` (runs `apply.sh`: clean clone of 4.2.11 in `work/`, git-ignored; never touches
`../cc2500-rxdiag/firmware/work/betaflight`). Uses the pinned docker/GCC 9.2.1 toolchain and downloads of
`../cc2500-rxdiag/firmware` (SOURCES.lock). Output `out/<BUILD_ID>/` (hex, bin, SHA256SUMS; only the sums are tracked).
The build log's "warning:" lines are the docker environment's (`python: not found`, git-not-a-repo), same as stock.
Current build id a7c24987: bin 431488 bytes, sha256 c24cfa44bd89...7dcc (full in `out/a7c24987/SHA256SUMS`). Older build f9420b39 (430792 B) is superseded.
The result is a bare target build (no cloud options), hence smaller than the stock cloud image.

## Recovery: stock image
`recovery/betaflight_4.2.11_MATEKF411RX.bin`, sha256 `bb32b85a705b76d75f470e9e10a3ec8db92e5bb6cc568504d2c4680dae912fc5`
(copied from `/Users/1unoe/Developer/personal/auto-drone/stage4/recovery/assets/`; same file as earlier restores).
Rollback (FC in DFU mode. Bench path without touching the board: Betaflight CLI `bl` (e.g. `bfcli.py PORT bl`), which reboots into the ROM DFU bootloader; or hold BOOT while plugging USB, `dfu-util -l` shows 0483:df11; no serial tool may hold the port):

    dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D bench/betaflight-patch/recovery/betaflight_4.2.11_MATEKF411RX.bin

Bench flashes (see `bench/d8-tx/results/betaflight-patch/flash_log_a7c_1.txt`) used the no-touch path: `bl` over the CLI, then the same `dfu-util ... -D <bin>` command.

Flashing wipes config: redo it per `bench/d8-tx/results/bf_link/RESTORE.md` (diff all replay, tx id 66,178, hop table,
spi offset -32, feature TELEMETRY, LEDs off). Flash the patched image the same way with `out/<id>/*.bin`.
