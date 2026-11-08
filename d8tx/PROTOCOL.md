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
| `TLM <every> [cap_us] [gain] [dec] [same] [stream] [ack]` | `OK every=.. cap_us=.. gain=.. dec=.. same=.. stream=.. ack=.. n=<samples> gain_max=..` | idle only (else `ERR busy`); RAM only. every 0 = off, else 4..940 slots. cap_us 500..12000 (default 10000), gain -1 = hardware AGC or 0..127 manual code (default 40, clamped to the chip's max), dec 16/32/64 (default 32), same 0 = listen on the next hop channel (default), 1 = on the trigger channel. cap_us*16/dec ≤ 6000. stream 0 (default) = blocking int16 dump; 1 = int8 payload shipped in the background while LINK keeps sending. ack 0 (default) = firmware advances tid +1 per trigger; 1 = host acks with `TID` |
| `TID <0..31>` | idle: `OK tid=<n>`; during LINK: no reply | idle: first tid of the next LINK (default 0). During LINK: replaces the tid for the next trigger in either mode (with ack=0 the firmware keeps adding +1 per trigger from the new value, so the host normally sends `TID` only with ack=1). With ack=1: the host sends tid+1 if it decoded a reply echoing tid, else the same tid (Betaflight's re-request rule). The next trigger waits for it (at most 1 s, then repeats the same tid) |
| `TCAP <khz> [cap_us] [gain] [dec] [pwr]` | `EV tlm ...` + payload, then `OK` | one capture at khz (2404000..2478000) + FOFS, no link. pwr −1 (default) = no keying; 0..127 = key one data packet (counter 0, current sticks) on that frequency first, then capture: exercises the same unkey→capture path. LO returns to 2412 MHz afterwards |

With `TLM every>0`, slot k of a `LINK` is a trigger when k ≥ every and k % every == 0 (use an every that is not a multiple of 47, e.g. 48, so triggers walk the hop table):
- The trigger packet has byte 3 = 2 (Betaflight replies when byte3 % 4 == 2) and byte 4 = telemetry id `tid` (0..31; ack=0: +1 per trigger; ack=1: set by the host with `TID`; starts at the idle `TID` value, default 0). All other packets keep byte 3 = 0 and byte 4 = the slot counter: Betaflight reads byte 4 only on trigger packets (it echoes it in the reply and acks hub data when it equals its expected id, last + 1), so data packets are accepted unchanged. With ack=0 a trigger the drone misses puts its hub ack id out of step for up to 32 triggers. With ack=1 the host advances only after a received reply, so it repeats a missed request and, starting out of step, walks into the drone's expected id within 32 received replies. Hub bytes only appear when the receiver has FEATURE_TELEMETRY on; with it off the hub count is always 0 (`bench/d8-tx/host/d8hub.py`).
- stream=1: with `TLM every>0`, slot k is a trigger when k ≥ the previous trigger + every and the previous capture has gone out (and, with ack=1, its `TID` arrived), instead of k % every == 0.
- Right after the trigger packet's last bit (same critical section) the radio is unkeyed, retuned to the listen channel (default: next table entry, because Betaflight calls `nextChannel(1)` before it transmits the reply ~1380 µs after the packet), the RX gain is set, and a 16 MS/s ring capture runs for cap_us, boxcar-decimated by dec on the CPU. Slot k+1 is never transmitted (the reply occupies it); after the capture the link resumes at the first future slot (≥ k+2) on the normal schedule, so a receiver keeps hopping in step (Betaflight waits up to 9 ms after starting its reply on k+1's channel, then moves to k+2's, ~0.6 ms before our k+2 packet). stream=0: slots that pass during the blocking dump are skipped (20 KB at dec 32 ≈ 0.22 s ≈ 24 slots; the receiver went into RX failsafe ~80% of the time with every=48). stream=1: no slot is skipped except k+1; the int8 conversion and the UART output run in the ~1.9 ms idle gaps between packets (≈9 KB at cap_us 9000 takes ≈27 slots), and no other text (status lines, `STAT` replies) is printed until it is out.
- Each capture is reported as one line followed by binary payload:
  `EV tlm k=<slot> ch=<listen channel> tid=<id> fs=<Hz> n=<samples> dec=<dec> turn_ns=<unkey start→capture start> run_us=<capture> g0=<gain idx first> g1=<gain idx last> lost=<pairs> bad=<sessions> late=<pairs> work=<cycles> units=<sessions> to=<0|1> bytes=<4n> crc=<crc32 hex>` then exactly `bytes` raw bytes (int16 little-endian I, Q interleaved, Q **not** negated: negate Q for RF = LO + f) then `\n`. stream=1 adds `bits=8 sh=<shift>` before `bytes=<2n>`: the payload is int8 I, Q (the int16 values arithmetically shifted right by sh so the peak fits). For `TCAP`: k=0, ch=<khz>, tid=1 if a packet was keyed first, else 0. crc32 = zlib.crc32 of the payload. This line is longer than the 95-char request limit; it is a device→host event.
- Only `S`, `TID`, `STOP`/`U` and `STAT` are handled while linked (`STAT` is dropped while a stream=1 capture is going out); `S` lines that arrive during a capture/dump are buffered and applied after it.
