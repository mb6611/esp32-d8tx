# Blackbox capture, decode and plot (MATEKF411RX, Betaflight 4.2.11)

Tools for getting Betaflight blackbox logs off the Tinyhawk FC and plotting them. The drone procedure was run on 2026-11-08: see `results/NOTES.md`. **Read it first**: on this F4
board Betaflight re-initialises USB whenever the shared VCP changes owner (arm and disarm), macOS then leaves the
port silent, and only a host USB reset (`usbreset.py`) brings it back. One log was recovered (header start rebuilt
with `reconstruct_header.py`); repeated resets hung the FC.

## Finding: no onboard log storage, so log over the USB VCP

Checked in `bench/cc2500-rxdiag/firmware/work/betaflight` (4.2.11, `948ba63`):

- `src/main/target/MATEKF411RX/target.h` defines no `USE_FLASH_*` chip (M25P16/W25N01G/W25M) and no `USE_SDCARD`,
  and has no SD card SPI or CS pins. `target.mk` lists `FEATURES += VCP SDCARD_SPI`, which only compiles the
  SD card sources. Without `USE_SDCARD`, `common_post.h` undefines `USE_SDCARD_SPI`/`SDIO`. Without a flash chip,
  `USE_FLASH_CHIP` is never set and `common_post.h` undefines `USE_FLASHFS`. So `blackbox_device` can only be
  `SERIAL` in practice: `blackboxValidateConfig()` forces anything else back to SERIAL. `common_pre.h` enables
  `USE_BLACKBOX` because the F411 has more than 64 KB of flash. `MSP_DATAFLASH_SUMMARY` answers `flags=0`.
- The default device is already SERIAL (`DEFAULT_BLACKBOX_DEVICE`, blackbox.c). No port has `FUNCTION_BLACKBOX`
  in the saved diffs (they only show `serial 1 2048 …`; VCP is default `serial 20 1 …`). That means blackbox is
  effectively off today. Arming calls `blackboxDeviceOpen()`, which fails and sets the state to DISABLED until
  reboot.

### Why these commands (`config/enable_serial_vcp.txt`)

```
serial 20 129 115200 57600 0 2000000
set blackbox_device = SERIAL
set blackbox_mode = NORMAL
set blackbox_p_ratio = 32
set blackbox_record_acc = ON
save
```

- `20` = `SERIAL_PORT_USB_VCP` (io/serial.h). `129` = `FUNCTION_MSP (1) | FUNCTION_BLACKBOX (128)`.
  `isSerialConfigValid()` requires MSP on the VCP. MSP may be shared with blackbox:
  `ALL_FUNCTIONS_SHARABLE_WITH_MSP` includes `FUNCTION_BLACKBOX`.
- The arguments are `serial <id> <mask> <msp> <gps> <telemetry> <blackbox baud>` (cliSerial, 6 required).
  USB ignores line rates. The blackbox baud only matters in `blackboxDeviceOpen()`. At 1 Mbaud or above, the
  header goes out at 64 B per loop. Below that it is capped at `targetPidLooptime*3/500`, about 1 B per loop at
  4 kHz, which delays the first frame by about 1 s. `2000000` is a valid index (`BAUD_2000000`).
- On arm, `blackboxUpdate(STOPPED)` calls `blackboxOpen()`. That runs `mspSerialReleasePortIfAllocated()` on the
  shared port, then opens it for BLACKBOX. After 100 ms the header (`H Product:Blackbox flight data recorder…`)
  is sent, then the I/P/S frames. On disarm it logs the `LOG_END` event (`E 0xFF "End of log\0"`), waits up to
  200 ms, closes the port and calls `mspSerialAllocatePorts()`, so MSP answers again.
- `blackbox_p_ratio 32` (default) means one frame per ms (`P interval` = I interval/32 at a 4 kHz PID loop) and an
  I-frame every 32 ms. The real rate depends on `pid_process_denom`; the log header records it.
- When a frame finds the VCP TX buffer full, its bytes are dropped (`blackboxWrite` checks
  `serialTxBytesFree`). They are not blocked, so the PID loop never stalls. Read the port continuously while
  armed.

Revert: `config/revert_serial_vcp.txt` (`serial 20 1 115200 57600 0 115200` plus the defaults), or replay the
saved `diff all`.

### Gotchas

- While armed, the drone port carries only blackbox bytes. MSP requests get no reply, and the request bytes queue
  up and are parsed after disarm. Stop `d8tx.server` and anything else that polls MSP on
  `/dev/cu.usbmodem0x80000001` before arming. Two processes reading one cu device split the bytes between them.
- Motor-test logging (`startInTestMode`) refuses a port shared with MSP, so only armed logging works here.
- If blackbox has failed to open once (for example, armed before the config was saved), it stays DISABLED until
  reboot.
- `exit` and `save` in the CLI both reboot the FC (`cliExit` calls `cliReboot`). While in the CLI, arming is
  blocked (`ARMING_DISABLED_CLI`).
- Arming needs the D8 link (ESP32 TX) and the overnight rule of USB power only. `bbcapture.py` reads
  `MSP_ANALOG` and `MSP_BATTERY_STATE` (decoded in `bbcapture.py`, not `bf_msp.parse_analog`) and refuses if any vbat
  field is above 0.5 V or a cell is detected. If it refuses on a drone you know is on USB, check with `bbcli.py run status`.
- blackbox-tools only reads a `P interval` written as `num/denom`. Betaflight 4.x writes a bare integer, so the
  decoder treats every iteration as logged. `loopIteration` in P-frames then counts up by 1 per frame, and the
  decoder reports "iterations missing". Time and all data fields are correct, and the plots use time. The
  Python parser copies this behaviour so the two outputs match.

## Files

| file | what |
|---|---|
| `bbcapture.py` | `serial` capture (raw → split → `.bbl`), `flash` MSP 70/71 downloader (exits 2 with "no onboard dataflash"), `split` offline |
| `bbcli.py` | CLI: `diff OUT`, `apply CONFIG [--save]` (stops and leaves with `exit` on `###ERROR`), `run CMD…` |
| `bbdecode.py` | `.bbl` → `<stem>.NN.csv` per log; `--engine c` (blackbox_decode), `py` (fallback), `auto` |
| `bbplot.py` | `.bbl` or `.csv` → `<stem>.NN.png`: gyroADC[0..2], setpoint[0..2], rcCommand[0..3], motor[0..3] vs time |
| `bbl.py` | stream splitter, MSP v1 scanner (jumbo), pure-Python parser (I/P/S/E, all BF 4.2 encodings; no GPS), BF-4.2 writer |
| `build_decoder.sh` | clones and builds `betaflight/blackbox-tools` at `d89f96b983d0f5c8f053acf003ee2998b02b5b0f` (master 2026-10-25) into `vendor/` (ignored) |
| `bbarm.py` | scripted arm sessions over the ESP32 D8 link (d8tx venv): arm at zero throttle, roll/pitch/yaw sweeps, small throttle bump, disarm; CSV of sticks sent |
| `usbreset.py` | libusb port reset of the FC so macOS re-enumerates the VCP (needs Homebrew libusb + pyusb) |
| `bbwatch_reset.py` | experimental capture used for the one good log: poll MSP, on loss one USB reset, then read |
| `reconstruct_header.py` | rebuild a lost header start (Product..Field S signed) for BF 4.2 field conditions |
| `make_sample.py` | regenerates `tests/data/sample_capture.raw` (synthetic, deterministic) |
| `config/` | enable/revert CLI files |
| `results/sample/` | the sample capture split, decoded with the C decoder, and plotted |

The decoder is pinned to a commit rather than the last tag, v0.4.3. That tag dates from 2017, before Betaflight
4.x, and master has 4.x fixes such as firmware-specific vbat scaling. `bbdecode.py` calls it with
`--unit-vbat raw --unit-amperage raw --unit-flags raw` so every column is numeric. Set `BLACKBOX_DECODE` to use
a different binary.

## Setup and tests

```
cd bench/blackbox
uv venv -p 3.14 .venv && uv pip install -p .venv/bin/python pyserial matplotlib pytest
./build_decoder.sh
.venv/bin/python -m pytest tests -q            # 27 passed
```

A local venv is used because the shared `python/.venv` (Python 3.15) has pyserial but not matplotlib.
`bbcapture.py` and `bbcli.py` also run under that venv. `bbcapture.py` imports `bench/d8-tx/host/bf_msp.py`
for the MSP frame helpers.

Test data: no public Betaflight 4.2 sample is vendored. `tests/data/sample_capture.raw` is generated by
`bbl.Writer`, which ports Betaflight 4.2's field table, predictors and encoders (`blackboxWriteTag2_3S32`,
`Tag8_4S16`, `Tag8_8SVB`, NEG_14BIT for vbat). The file holds an MSP reply, log 1 (600 frames), an MSP reply,
log 2 (400 frames) and another MSP reply. Its sha256 is
`47e9aa4c98cd7c34d99b6f1152ef037ccb7bde549af46c9fa67d3e15858f2b1b`, pinned in the test. The tests check:
encoder round trips; splitting (complete, truncated and none); jumbo MSP; `record()` stopping on LOG_END and on
idle; the vbat check; flash download against a fake FC, with and without flash; CLI apply and error abort; the
Python parser against ground truth; the C decoder matching the Python parser column for column (on synthetic data; on the real log the parser has 14 extra start frames and misses one frame, all shared cells match); and multi-log
PNG output with both engines.

## Bench procedure (drone on USB only, no battery; hold `/tmp/d8tx-hw.lock`)

```
P=/dev/cu.usbmodem0x80000001; E=bench/blackbox/results/<run>; mkdir -p $E
pkill -f d8tx.server                                       # frees the drone port
.venv/bin/python bbcli.py diff $E/diff_all_before.txt --port $P
.venv/bin/python bbcli.py apply config/enable_serial_vcp.txt --save --log $E/apply.log --port $P
.venv/bin/python bbcli.py diff $E/diff_all_after.txt --port $P   # expect 'serial 20 129 … 2000000'
.venv/bin/python bbcapture.py serial --port $P --out $E --sessions 1 --confirm-msp
#   ... arm via the D8 TX, hold for a while, disarm; the tool stops on LOG_END (or idle 3 s / Ctrl-C)
.venv/bin/python bbplot.py $E/bb_*.bbl --outdir $E          # decode + PNG per log
# revert when done (or keep it enabled; it only acts while armed):
.venv/bin/python bbcli.py apply config/revert_serial_vcp.txt --save --port $P
.venv/bin/python bbcli.py diff $E/diff_all_reverted.txt --port $P
```

Flash-equipped boards: `bbcapture.py flash --port $P --out DIR`, then `bbplot.py DIR/flash_*.bbl`.
