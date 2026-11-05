# Live view (rtl_tcp bridge)

## U8.1 – z2labs/esp-sdr-bridge (research only, not run on the board)

Read on GitHub (https://github.com/z2labs/esp-sdr-bridge):

- License: **GPL-3.0** (same as ours); not vendored.
- Target: **ESP32-S3** native USB Serial/JTAG, opened at 2 000 000 baud, with the
  S3-only firmware branch `zodoczi/esp-sdr@s3-iq-stream` (PIE-SIMD two-stage FIR DDC).
- Serves SpyServer and rtl_tcp; sends `FREQ`, `FOFS`, `GAIN MANUAL`, and
  `IQS 0 <dec> <bits> <code> <shift> <mode>` with its own mode 2 (fs/4 IF), a 16 MS/s
  ring and S3 gain table, output rates 250/125/62.5 kS/s.
- Verdict: **does not fit the classic ESP32 DevKit V1**: wrong chip/port/baud (921600 UART
  here), assumes S3 firmware behaviour (DDC mode 2, 16 MS/s, tuning 2204–2804 MHz) and
  our IQS grammar differs (`IQS <ms> <dec> <bits> <rate>`, rates/dec limited by the UART
  link budget). Adapting it would mean patching most of it, so we use our own bridge.

## U8.2 – `esp32sdr bridge`

    esp32sdr --port /dev/cu.usbserial-XXXX bridge --listen 127.0.0.1:1234 --freq 2402 --dec 512 --bits 8

- rtl_tcp: 12-byte header `RTL0` + tuner type 5 + gain count 29, then u8 offset-binary
  interleaved I/Q (signed samples scaled to 8 bit, +128).
- Command 0x01 (set frequency, Hz) → whole MHz for `FREQ`, remainder as `FOFS` kHz
  (clamped ±1000); the stream is stopped (newline), re-tuned and `IQS 0 ...` restarted.
  Frequencies outside 1850–2500 MHz are ignored, and so is a request for the frequency
  already tuned (no IQS restart). The board's rate is `RATE/dec` (31250 S/s at dec 512).
  Command 0x02 (sample rate): if the client asks for an integer multiple k ≤ 128 of that
  rate, the bridge interpolates by k (zero-stuff + Kaiser sinc, unity gain) so the client's
  frequency axis is right; any other request (including 31250 from gqrx, or no request)
  gets native samples. Only SDR++ needs this (its RTL-TCP source offers 250 kS/s and up:
  250000 = 8 × 31250). Gain and other commands are ignored.
- `--offset-mhz N` is added to every requested frequency. Needed for gqrx: gr-osmosdr's
  rtl_tcp source (`rtl_tcp_source_c.cc`, `get_freq_range`) clamps to 24–1766 MHz for tuner
  type 5 (R820T), and to 52–2200 MHz for an unknown/E4000 tuner, so 2.4 GHz is unreachable
  by any header value (gqrx then sent 24 / 871 / 247.99 MHz when 2480 was typed).
  Workaround: run `bridge --offset-mhz 2000` and in gqrx set the LNB LO to 2000 MHz.
  gqrx sends displayed − LO to the device (2480 → 480 MHz), the bridge adds 2000 → 2480.
  Steps: start the bridge; gqrx → Configure I/O devices → device string
  `rtl_tcp=127.0.0.1:1234`, input rate 31250 (or nearest; the rate command is ignored);
  in Input controls set "LNB LO" to `2000.000 MHz`; type the frequency (e.g. 2480.000 MHz)
  directly. Usable displayed range is 1850–2500 MHz.
- One client at a time; a disconnect stops the stream. The listening default is loopback.
- Tests: `host/tests/test_rtltcp.py` (fake live stream + socket client).
- U8.3 (gqrx on real hardware) is still to do.

## U8.3 scripted check on the real board (2026-11-05)

A Python rtl_tcp client against the running bridge confirmed the RTL0 header, ~31.1 kS/s sustained, retunes 2400 → 2483 → 2426 MHz with samples flowing after each, and clean disconnect/reconnect; the board stayed healthy. Details in `bench-results.md`. The gqrx waterfall check (U8.3) remains manual.

## One command: SDR++ live view (`esp32sdr sdrpp`)

    host/.venv/bin/esp32sdr sdrpp            # --freq 2480 --dec 512 --bits 8 are the defaults

SDR++ (nightly, `/Applications/SDR++.app`; config in `~/Library/Application Support/sdrpp`)
replaces gqrx as the recommended viewer. The command:

1. stops any esp32sdr process holding the TCP port or the serial port (SIGTERM; the bridge
   releases the board on SIGTERM), and quits SDR++ (it rewrites its config on exit);
2. backs up `config.json`, `rtl_tcp_config.json`, `rigctl_server_config.json` and
   `radio_config.json` to `esp32sdr-backup-<date>-<time>/` in the SDR++ dir, then sets: source RTL-TCP
   on `127.0.0.1:1234` at 250 kS/s, SDR++ decimation 8 (span back to 31.25 kHz), centre
   frequency `--freq`, centre tuning on, FFT 1024 at 25/s (30 Hz bins), waterfall range
   −110…−40 dB, radio muted and set to NFM 12.5 kHz (the default 150 kHz WFM VFO does not fit
   the span and pulled the centre 59 kHz off), rigctl server auto-started on port 4532;
3. runs the same code path as `esp32sdr bridge` (`rtltcp.cmd_bridge`); once it listens it
   launches SDR++ and sends `\start` to the rigctl server until SDR++ connects, so
   playback starts with no clicks. If that fails it prints which button to press (play,
   top left).

Ctrl-C (or `kill`) stops the bridge; SDR++ stays open. Running `esp32sdr bridge --freq 2480`
plus SDR++ configured by hand (RTL-TCP, 250 kHz, decimation 8) behaves identically.
SDR++'s RTL-TCP source sends the frequency as a u32 in Hz, so there is no clamp and no
`--offset-mhz`; type the real frequency (1850–2500 MHz). Remote retune:
`printf 'F 2402000000\n' | nc 127.0.0.1 4532`.

## Bridge robustness (2026-11-05)

Failure seen with gqrx: `client ended: TransferError: IQS stream failed: short read 1006/1028`.
Root cause, reproduced on the board: while gqrx's DSP is off it does not read the socket,
so the bridge blocked in `sendall`, stopped reading the serial port, and the USB-serial
buffer overflowed. A frame cut short by the dropped bytes then "absorbed" the following
bytes; when the stream ended (retune STOP), its payload read swallowed the `IQSEND` line and
waited for bytes that never came, the transport discarded what it had, and the client was
dropped. (Reproduced: bridge + gqrx with DSP off, then quitting gqrx → `short read 1027/1028`.)

Fixes:

- `rtltcp.py`: a sender thread with a 64-block queue does the TCP writes; the serial reader
  never waits on the client and drops blocks (counted: "blocks dropped for a slow client")
  when the queue is full. Send buffer 64 KiB bounds the stale backlog.
- `iqs.py` / `transport.py`: `SerialTransport.read_some` loses nothing on timeout; the IQS
  reader waits the full timeout only for the first byte of a read and 0.5 s once a frame
  has started, then treats it as cut short (`short_frames`), slips one byte and rescans,
  which finds the next frame or the `IQSEND` line.
- `rtltcp.py`: an IQS run that fails or that the firmware ends by itself is logged with its
  loss and restarted; only 5 consecutive runs with no data end the client. A status line
  every 30 s reports samples, lost samples, short frames, bad CRCs and dropped blocks.

Bench check (2026-11-05, DevKit V1, 921600): a scripted gqrx-like client that stopped
reading for 40 s, then retuned 2480 (no restart, already tuned) and 2402: stream kept
running, 31.25 kS/s after the backlog flushed, 0 lost samples, 1735 blocks dropped while it
was not reading. `esp32sdr sdrpp` with real SDR++: auto play, >2.5 min continuous, rigctl
`F 2402000000` and back to 2480 (SDR++ `f` confirms each), every 30 s status 936448
samples (31215 S/s), 0 lost, 0 short frames, 0 bad CRC, 0 dropped; socket queues empty
(SDR++ keeps up).

## Built-in waterfall in d8live (2026-11-05)

For the D8 work there is also a browser waterfall that needs no SDR program: the Waterfall
tab of `esp32sdr d8live` (`http://127.0.0.1:8765/#waterfall`). It shows ±125 kHz around the
tuned frequency, or with `--follow` a hop map with one strip per hop channel. Rows are made on
the host (256-point FFT, 25 rows/s) only while the tab is open. It is not an rtl_tcp client
and does not replace the bridge for general use. See `host/web/d8live/README.md` and
`hop-follow.md`.
