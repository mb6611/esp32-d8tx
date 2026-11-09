# Patched Betaflight 4.2.11 (MATEKF411RX): richer FrSky hub telemetry

Patch 0001 (`patches/0001-frsky-hub-telemetry.patch`) changes only `src/main/telemetry/frsky_hub.c`: true milli-g ACC (stock
truncates to whole g), STATUS 0x46, ARMING_DISABLE 0x47, gyro 0x40-0x42, attitude 0x43-0x45. Encoding, rates and
byte budget: `protocol/PROTOCOL.md` "Patched Betaflight hub fields". Patch 0002 (`0002-matekf411rx-icm20689.patch`, ICM20689 gyro support) also changes `target/MATEKF411RX/target.h` and `target.mk`. Everything else is stock.

## Build
`./build.sh` (runs `apply.sh`: clean clone of 4.2.11 in `work/`, git-ignored; never touches
`../cc2500-rxdiag/firmware/work/betaflight`). Uses the pinned docker/GCC 9.2.1 toolchain and downloads of
`../cc2500-rxdiag/firmware` (SOURCES.lock). Output `out/<BUILD_ID>/` (hex, bin, SHA256SUMS; only the sums are tracked).
The build log's "warning:" lines are the docker environment's (`python: not found`, git-not-a-repo), same as stock.
Patch 0003 (`patches/0003-frsky-d-fast-block.patch`): FAST block + hub-timer-stall guard, see below.
Current build id c3f351e4 (patches 0001-0003): bin 432016 bytes, sha256 59c9b279b3d488792d0d04001203ec80bd85d2db15f9fc06afb044e7e916f039 (`out/c3f351e4/SHA256SUMS`). Flashed and bench-verified 2026-11-08 (`bench/d8-tx/results/fast-telemetry/e2e/flash_log.txt`). Previous a7c24987 (431488 B, patches 0001+0002) and f9420b39 are superseded.
The result is a bare target build (no cloud options), hence smaller than the stock cloud image.

## Recovery: stock image
`recovery/betaflight_4.2.11_MATEKF411RX.bin`, sha256 `bb32b85a705b76d75f470e9e10a3ec8db92e5bb6cc568504d2c4680dae912fc5`
(copied from `/Users/1unoe/Developer/personal/auto-drone/stage4/recovery/assets/`; same file as earlier restores).
Rollback (FC in DFU mode. Bench path without touching the board: Betaflight CLI `bl` (e.g. `bfcli.py PORT bl`), which reboots into the ROM DFU bootloader; or hold BOOT while plugging USB, `dfu-util -l` shows 0483:df11; no serial tool may hold the port):

    dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D bench/betaflight-patch/recovery/betaflight_4.2.11_MATEKF411RX.bin

Bench flashes (see `bench/d8-tx/results/betaflight-patch/flash_log_a7c_1.txt`) used the no-touch path: `bl` over the CLI, then the same `dfu-util ... -D <bin>` command.

Flashing wipes config: redo it per `bench/d8-tx/results/bf_link/RESTORE.md` (diff all replay, tx id 66,178, hop table,
spi offset -32, feature TELEMETRY, LEDs on: LED C13, RX_SPI_LED B09, LED_STRIP; simplest is replaying the saved pre-flash `diff all`). Flash the patched image the same way with `out/<id>/*.bin`.

## Patch 0003: FAST telemetry block (design: `.ru/plans/fast-telemetry.md`)
`src/main/rx/cc2500_frsky_d.c`, `appendFrSkyHubData()` (+ `buildFastBlock()`, `frSkyDPackFast()`): reply `cnt` byte (frame[6]) is 0x8A and
the 10 payload bytes are the FAST block (roll/pitch/yaw deci-deg, gyro xyz 0.25 deg/s filtered, 2-bit seq; bit layout in the design) on every
reply except each `FAST_HUB_EVERY`-th (3) hub slot; a hub slot with nothing to send is fast too. Ack rule unchanged in spirit: the `telemetryIdExpected`
match (ack of previous hub bytes, expected+1) now runs on every reply incl. fast ones, because the host acks the previous hub reply in whatever slot follows;
fast replies load/send/consume no hub bytes. New-data refill happens only in a hub slot on a match. `telemetryBytesGenerated` is cleared when acked
(not in the send loop), and `telemetryBytesAcknowledged` is zeroed on refill, so a resend cannot replay stale bytes.
`src/main/telemetry/frsky_hub.c`, `processFrSkyHubTelemetry()`: cycle gate uses unsigned `(uint32_t)(now - last)` instead of signed `cmpTimeUs` (hub stall fix).
Hub gyro/attitude ids 0x40-0x45 are unchanged (kept). Offline check: `python3 check/fast_block_check.py` compiles the C packer extracted from the patch and
compares it with a Python pack/unpack (2005 cases). Note: the design text said "0.25 deg/s, same as 0x40" but 0x40 is 0.1 deg/s; the FAST block uses 0.25 deg/s.
