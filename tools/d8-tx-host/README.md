# tools/d8-tx-host

**TX research (educational; radiated indoors at bench range; see the [regulatory status](../../docs/lab-log/tx.md#regulatory-status) and check your local regulations):** the ESP32 (`firmware/`, app `d8tone`) speaking FrSky D8: first one packet, received by a receive-only CC2500 diagnostic on an STM32 board (`../cc2500-rxdiag/`), then hopping, control, telemetry and bind. Story and figures: [TX HTML write-up](../../docs/lab-log/index.html#tx-chapter) ([Markdown](../../docs/lab-log/tx.md), chapter source).

## Verified result (one packet, one batch)
Receiver tuned to 2412000 kHz, E8 off, 10 PKT sent at power 127, vector `1142b2000001cacacaca8888cacacaca8888` (CRC `afa7` appended by firmware): 7 of 10 received with hardware CRC_OK=1 and bytes equal to the vector; the real E8 control at 2421032 kHz gave 32 CRC-valid packets, source-off noise none CRC-valid. Details: [experiments/05-first-packet](../../experiments/05-first-packet/README.md) (`data/NOTE.md`, `data/analysis_batch1.txt`).

Caveats: ESP readback (`K,pkt`) is timing, not RF proof; the proof is the independent CC2500 CRC. Bench distance/attenuation unknown. Not hopping, control/flight, RF calibration or Betaflight restoration; the Tinyhawk-style board is not restored to Betaflight.

## Offline checks (no hardware, no flashing)
```sh
python3 -m unittest discover -s tools/d8-tx-host/tests       # host runner, vectors, rxdiag parsers
bash firmware/test/run.sh                   # C tests: command parser, line input, packet builder
make -C tools/cc2500-rxdiag/tests test                  # receive-only diagnostic simulation
(cd tools/cc2500-rxdiag/firmware/out/4bdc8581 && shasum -a 256 -c SHA256SUMS)   # artifact checksums
```
Each experiment's README says how to regenerate its figures from its `data/` (needs matplotlib), e.g. `python3 experiments/05-first-packet/scripts/plot_tx.py`.

## Evidence and checksums
Raw logs live in [`experiments/`](../../experiments/README.md) (packet milestone: `experiments/05-first-packet/data/`). Artifact references:
- ESP `d8tone.bin` sha256 `3698ae6f6bbe0b11bfac103c9f008320d9d90dfe9d22d179d55da0bcd5c60461` (`experiments/05-first-packet/data/esp_hashes.txt`; the build tree is not in git).
- STM `betaflight_4.2.11_MATEKF411RXDIAG_.bin` sha256 `06e88ff2aa8bb68e34f3e8d61834b674d2b7670b10017a3684fdaa6eeb8b3961`, BUILD_ID `4bdc8581` (`experiments/05-first-packet/data/stm_checksum_verify.txt`, `../cc2500-rxdiag/firmware/out/4bdc8581/SHA256SUMS`).
`check_source.py` and `check_build.sh` need the Betaflight work tree (git-ignored, not in this clone) so it is not an offline check here.

## Host runner details
Host side: `host/d8_vectors.py` (independent E8 D8 packet builder),
`host/bench_runner.py` (serial runner, timestamped JSONL log, phases
`source-off` / `real-e8-control` / `esp32-test`).

## STM reports (rxdiag proto=3 freq mode)
`parse_report` accepts exactly the real emitter's `H,proto=3,mode=freq,...` (all keys, in order),
`F,seq,t_us,n,rej,ncs,fe_last,fe_min,fe_max,fe_mean_raw,fe_mean_hz,rssi_max_raw,pktstatus_last,lqi,marc,flags`
and `X,seq,t_us,done|host|radio|usb|usbstall`. A window with `ncs=0` must carry flag 16
(no carrier) and zero frequency estimates (`carrier=False`). Anything else, wrong
field counts, out-of-range values, inconsistent flags, or a line without its newline
(`Runner.read_report`) raises `ReportError`.

## ESP commands (d8tone)
`Runner.command` is the only way to write to the ESP. Commands are validated against
the firmware grammar (`cmd_parse.c`): only `PING STAT U TONE ALT PKT` (verb matched
case-insensitively on the host; the firmware itself is case-sensitive), decimal
arguments, <=95 chars, no control characters, firmware limits (|f|<=511, dur 50..200000 us,
half>=50 and <=255 transitions, power 0..127, omitted power = 127). Unknown or
malformed commands are refused before anything is written.

TONE/ALT in any letter case need phase `esp32-test` plus `Runner.authorize(Envelope(...))`;
`Envelope(test, max_duration_us, max_abs_offset, max_power, max_transitions, max_commands)`
has no defaults. Each keying command is checked against the envelope and consumes one
`max_commands`; leaving the phase clears it.

Replies are read until `OK` / `ERR <why>` with a timeout (`reply_timeout_s` plus the
command duration, or `timeout_s=`), every line logged with a timestamp. TONE/ALT replies
must be `K,...` echoing the command, `ntrans` `T,...` lines, then `OK`; a malformed reply
or timeout on a keying command sends `U` and raises. `I,boot` mid-command raises.
Returns `Reply(ok, lines, error, records)`.

Offline tests: `python3 -m unittest discover -s tools/d8-tx-host/tests`

## Host runner: one-packet stage (offline-tested)

- `PKT <36|40 hex> [pwr]` is an RF command (any case): needs phase `esp32-test` and an `Envelope` with
  `max_packets >= 1` (default 0 = forbidden), `max_duration_us >= 6700`, `max_abs_offset >= 1` and
  `max_power >= pwr` (omitted pwr counts as 127). Each PKT consumes one packet and one command.
- The `K,pkt,...` reply is validated (bits=208, pwr echo, on_us 6700..6800, key/unkey cycles,
  max_late_ns, `b8_off` bit18 clear); any failure auto-sends `U`.
- `parse_pkt_record()` strictly parses `rxdiag pkt` H(proto=4)/P/E/X lines;
  `compare_p_to_vector(p, vec)` returns field-by-field diffs against a `d8_vectors.build()` vector.
  The CC2500 strips the 2 CRC bytes, so a whole P record carries 18 bytes (length + 17 payload) plus
  `crc_ok`; the comparison uses the 18-byte body and requires `crc_ok=1` (a 20-byte record is accepted
  only if the vector's own CRC matches).
- Key/unkey cycle and late-ns limits are host-chosen guesses (200 µs, 5000 ns), not firmware-derived.
- Tests: `python3 -m unittest discover -s tools/d8-tx-host/tests`.
