# d8tx UART protocol v1

ASCII lines at 921600 8N1. Lines end in `\n` (`\r\n` accepted), at most 95 characters (longer → `ERR long`). Every request gets exactly one final reply, `OK[ k=v ...]` or `ERR <code> <text>`. Asynchronous events are `EV <name>[ k=v ...]`. Error codes: `args`, `range`, `busy`, `keyed`, `unknown`, `long`.

| Command | Reply | Notes |
|---|---|---|
| `PING` | `OK proto=1` | |
| `INFO` | `OK proto=1 fw=d8tx-v1 slot_us=8994 channels=47 pwr_max=127 fofs_max_hz=200000 timeout_max_ms=1000` | |
| `STAT` | `OK keyed=0\|1 link=0\|1 fofs=<hz> armok=0\|1` | also while linked |
| `FOFS <hz>` | `OK` | signed, \|hz\| ≤ 200000, idle only; else `ERR range` |
| `ARMOK` | `OK` | allows ch7 > 1300 for the next `LINK` only; cleared when it ends |
| `LINK <pwr> [timeout_ms]` | `OK`, then continuous hopping | pwr 0..127; timeout 1..1000, default 300 |
| `S c1..c8` | none while linked; `OK` when idle | µs, clamped 1000–2000; ch7 ≤ 1300 unless ARMOK |
| `STOP` (alias `U`) | `OK` | ends the link (the `EV link_end` precedes the `OK`) |

Channel order TAER1234 (ch1 throttle, ch2 roll, ch3 pitch, ch4 yaw, ch5–8 AUX1–4); ARM = ch7.

## Events
- `EV boot reason=<n>` at reset (RF-silent; any link or ARMOK is gone).
- `EV link slots=<n> late_max_us=<n>` once per second while linked.
- `EV link_end why=stop|timeout|err slots=<n> late_max_us=<n> retune_max_us=<n>`. `timeout` (no `S` for timeout_ms) has no reply line; `stop` is followed by `OK`; `err` by the `ERR` line for the offending request.

## Linked behaviour
While linked, `S`, `STOP`/`U` and `STAT` are handled. Any other request ends the link with `EV link_end why=err` then `ERR busy link active`. A malformed line (bad `S`, overlong line) also ends the link with its own error (`ERR range ...`, `ERR args ...`, `ERR long ...`). `LINK` while keyed → `ERR keyed`.

## Error mapping
`args` wrong argument count or malformed hex; `range` a value out of range or non-numeric; `busy` link active; `keyed` radio is keyed; `unknown` unknown command; `long` line too long.

## Legacy bench commands
`TONE`, `ALT`, `RETUNE`, `PKT`, `HOP`, `STICKS` still exist but are not part of the API. They keep their old bare `ERR <why>` replies and `K,...` report lines. `HOP 0 <pwr> [timeout]` is the legacy twin of `LINK`. Changed vs. the earlier bench firmware: `PING` is `OK proto=1` (was `P,d8tone,1`), `STAT` is the v1 form (was `S,keyed=...`), boot line is `EV boot` (was `I,boot`), and the `I,ready` line is gone.

## Telemetry listen (experiment, off by default)
Bench-only extension for listening to Betaflight's FrSky D8 telemetry reply. Not used by the d8tx library or app; with `TLM 0` (the boot default) `LINK` behaves exactly as above. Host: `bench/d8-tx/host/tlm_listen.py`.

| Command | Reply | Notes |
|---|---|---|
| `TLM <every> [cap_us] [gain] [dec] [same]` | `OK every=.. cap_us=.. gain=.. dec=.. same=.. n=<samples> gain_max=..` | idle only (else `ERR busy`); RAM only. every 0 = off, else 4..940 slots. cap_us 500..12000 (default 10000), gain -1 = hardware AGC or 0..127 manual code (default 40, clamped to the chip's max), dec 16/32/64 (default 32), same 0 = listen on the next hop channel (default), 1 = on the trigger channel. cap_us*16/dec ≤ 6000 |
| `TCAP <khz> [cap_us] [gain] [dec] [pwr]` | `EV tlm ...` + payload, then `OK` | one capture at khz (2404000..2478000) + FOFS, no link. pwr −1 (default) = no keying; 0..127 = key one data packet (counter 0, current sticks) on that frequency first, then capture: exercises the same unkey→capture path. LO returns to 2412 MHz afterwards |

With `TLM every>0`, slot k of a `LINK` is a trigger when k ≥ every and k % every == 0 (use an every that is not a multiple of 47, e.g. 48, so triggers walk the hop table):
- The trigger packet has byte 3 = 2 (Betaflight replies when byte3 % 4 == 2) and byte 4 = telemetry id `tid` (0..31, +1 per trigger, starts at 0 for each LINK). All other packets keep byte 3 = 0 and byte 4 = the slot counter: Betaflight reads byte 4 only on trigger packets (it echoes it in the reply and acks hub data when it equals its expected id, last + 1), so data packets are accepted unchanged. The firmware does not decode, so it cannot re-request: if the drone misses a trigger its hub ack id falls out of step and it keeps resending the same hub bytes (A1/A2/RSSI still fresh).
- Right after the trigger packet's last bit (same critical section) the radio is unkeyed, retuned to the listen channel (default: next table entry, because Betaflight calls `nextChannel(1)` before it transmits the reply ~1380 µs after the packet), the RX gain is set, and a 16 MS/s ring capture runs for cap_us, boxcar-decimated by dec on the CPU. Slot k+1 is never transmitted (the reply occupies it); after the dump the link resumes at the first future slot (≥ k+2) on the normal schedule, so a receiver keeps hopping in step. Slots that pass during the dump are skipped (20 KB at dec 32 ≈ 0.22 s ≈ 24 slots).
- Each capture is reported as one line followed by binary payload:
  `EV tlm k=<slot> ch=<listen channel> tid=<id> fs=<Hz> n=<samples> dec=<dec> turn_ns=<unkey start→capture start> run_us=<capture> g0=<gain idx first> g1=<gain idx last> lost=<pairs> bad=<sessions> late=<pairs> work=<cycles> units=<sessions> to=<0|1> bytes=<4n> crc=<crc32 hex>` then exactly `bytes` raw bytes (int16 little-endian I, Q interleaved, Q **not** negated: negate Q for RF = LO + f) then `\n`. For `TCAP`: k=0, ch=<khz>, tid=1 if a packet was keyed first, else 0. crc32 = zlib.crc32 of the payload. This line is longer than the 95-char request limit; it is a device→host event.
- Only `S`, `STOP`/`U` and `STAT` are handled while linked, as before; `S` lines that arrive during a capture/dump are buffered and applied after it.
