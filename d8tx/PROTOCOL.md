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
