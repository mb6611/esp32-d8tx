# d8tx UART protocol v1

ASCII lines at 921600 8N1. Lines end in `\n` (`\r\n` accepted), at most 95 characters (longer → `ERR long`). Every request gets exactly one final reply, `OK[ k=v ...]` or `ERR <code> <text>`. Asynchronous events are `EV <name>[ k=v ...]`. Error codes: `args`, `range`, `busy`, `keyed`, `unknown`, `long`, `bench-only`.

| Command | Reply | Notes |
|---|---|---|
| `PING` | `OK proto=1` | |
| `INFO` | `OK proto=1 fw=d8tx-v1 slot_us=8994 channels=47 pwr_max=127 fofs_max_hz=200000 timeout_max_ms=1000 txid=<xxxx> ver=<semver>+<hash8> bench=<0\|1>` | txid = this ESP's identity (4 hex digits, lowercase); ver = firmware build version (text, never a number; see "Firmware version"; `bench=` follows it). `pwr_max` = the build's compile-time power cap (`CONFIG_D8_PWR_MAX`, default 127). `bench` = 1 only in a `CONFIG_D8_BENCH` build; the last key. Hosts must ignore unknown keys and treat missing ones as absent: older firmware has no `bench` (assume 0, release command set) and may lack `pwr_max` (assume 127) |
| `STAT` | `OK keyed=0\|1 link=0\|1 fofs=<hz> armok=0\|1 bind=0\|1` | also while linked or binding |
| `FOFS <hz>` | `OK` | signed, \|hz\| ≤ 200000, idle only; else `ERR range` |
| `ARMOK` | `OK` | allows ch7 > 1300 for the next `LINK` only; cleared when it ends |
| `LINK <pwr> [timeout_ms]` | `OK`, then continuous hopping | pwr 0..`pwr_max` (raw PBUS code, see "Power"); timeout 1..1000, default 300 |
| `S c1..c8` | none while linked; `OK` when idle | µs, clamped 1000–2000; ch7 ≤ 1300 unless ARMOK |
| `STOP` (alias `U`) | `OK` | ends the link or bind (the `EV link_end` / `EV bind_end` precedes the `OK`) |
| `ID` | `OK txid=<xxxx> start=<s> step=<t>` | this ESP's identity (see "Bind") |
| `ID <xxxx> <s> <t>` | same as `ID` | set + persist (clone/restore a binding); hex txid, decimal start 0..255, step 1..255; `ERR range hop_table` if the table is not valid; idle only |
| `ID new` | same as `ID` | new random identity, persisted; bound receivers must re-bind; idle only |
| `BIND [pwr]` | `OK`, then bind packets | pwr 0..`pwr_max` (default `pwr_max`; the TS host sends 40); until `STOP` or 30 s; idle only. Bind packets go out on one fixed channel (hop channel 0), they do not hop; see "Bind" |

## Power
`pwr` is a raw PBUS(5,1) code on the ESP32's DAC path, **not dBm**, and there is no calibration: the output level at a given code has not been measured. The firmware rejects `pwr` above `pwr_max` (compile-time `CONFIG_D8_PWR_MAX`, default 127) with `ERR range`/`ERR pwr`. The host stack defaults LINK to **127** and clamps any requested power to the `pwr_max` it read from `INFO` (it reads `INFO` before `LINK`; with no `pwr_max` key it assumes 127).

## Release and bench command sets
Release build (`CONFIG_D8_BENCH=n`, the default; `INFO` shows `bench=0`): `LINK`, `S`, `STOP`/`U`, `FOFS`, `ARMOK`, `INFO`, `STAT`, `TLM`, `TLMX`, `PING`, `ID`, `TID`, `BIND`, `HOP 0 <pwr> [timeout_ms]` (continuous 47-channel hop) and receive-only `TCAP` (pwr −1). Every keying command in this set is the 47-channel hopping link or the bind transmission.

Bench build (`CONFIG_D8_BENCH=y`, `INFO` shows `bench=1`) adds the fixed-channel and CW modes: `TONE`, `ALT`, `RETUNE`, `PKT`, `HOP <n_slots> [pwr]` (n_slots > 0) and keyed `TCAP`. `pwr` is optional there (default `pwr_max`). A release build answers them `ERR bench-only` (keyed `TCAP`: `ERR bench-only bench build required`). The bench commands are documented in `firmware/main/d8tone.c` and `docs/lab-log/tx.md`; they are for bench experiments, not for flying.

## Identity
TX ID and hop table are per ESP: the firmware stores `{txid, start, step}` in NVS, draws a random one on first boot, and `INFO`/`ID` report it (`txid=`, `start=`, `step=`). There is no build-time TXID or hop table. Hosts use the device's `txid` from `INFO`/`ID` (the TS and Python stacks both do; telemetry replies must carry it) and never a constant; see "Bind".

Channel order TAER1234 (ch1 throttle, ch2 roll, ch3 pitch, ch4 yaw, ch5–8 AUX1–4); ARM = ch7.

## Events
- `EV boot reason=<n>` at reset (RF-silent; any link or ARMOK is gone).
- `EV link slots=<n> late_max_us=<n>` once per second while linked.
- `EV bind_end why=stop|timeout slots=<n>` when `BIND` ends; `stop` is followed by `OK`, `timeout` (30 s) has no reply line.
- `EV link_end why=stop|timeout|err slots=<n> late_max_us=<n> retune_max_us=<n> gap_max_us=.. gap50=.. gap100=.. gap200=.. g2_min_us=.. g2_max_us=.. trig=.. retry=..`. gap = packet start minus the previous packet start minus 8994 us (gapN: consecutive slots with |gap| > N us; g2: first slot after a skipped one); trig/retry: telemetry triggers sent / re-triggers. `timeout` (no `S` for timeout_ms) has no reply line; `stop` is followed by `OK`; `err` by the `ERR` line for the offending request.

## Linked behaviour
While linked, `S`, `STOP`/`U` and `STAT` are handled. Any other request ends the link with `EV link_end why=err` then `ERR busy link active`. A malformed line (bad `S`, overlong line) also ends the link with its own error (`ERR range ...`, `ERR args ...`, `ERR long ...`). `LINK` while keyed → `ERR keyed`.

## Bind
Each ESP has its own identity `{txid0, txid1, start, step}` in NVS (namespace `d8tx`, key `ident`, 4-byte blob). On the first boot without a stored (valid) identity the firmware draws a random one (`esp_random`) and stores it. The hop table is `d8_hop_table(start, step)`: entry 0 = 0 (the bind channel), entry i = (start + step·i) mod 256 for i = 1..46. Data packets carry txid0, txid1 in bytes 1, 2.

Valid identity (`ID <xxxx> <s> <t>`, `firmware/main/packet.c` `d8_ident_valid`): any txid; step ≠ 0; entries 1..46 pairwise distinct and each in 2..246 (0 is the bind channel and Betaflight's list-end marker, 1 equals bind byte 17 which Betaflight also treats as list end, 246 = 2477.78 MHz is the top of our LO range). The E8 binding `42b2 2 55` is valid. Generated identities (`ID new`, first boot, `d8_ident_good`) also keep every entry ≤ 234 and off 0x5a/0xdc (the reference TX's range and filter, below), use txid0 ∉ {0x00, 0x03, 0xff}, and must spread over the band like a real D8 table: consecutive hops (entries 0..46, cyclic) are ≥ 30 channels (≈9 MHz, the reference D8 step 0x1e) apart, and the used channels leave no gap > 32 channels within 2..234 (band edges included). 142 of the 65536 start/step pairs qualify (steps 43, 65, 73, 84, 103, 110 and their negatives mod 256); the earlier rule without the spread checks also accepted steps 1–5 and 251–255, which packed all 47 hops into a ~14 MHz slice. `ID <xxxx> <s> <t>` keeps the permissive rule, so clones such as the E8 table (2, 55) still load.

`BIND` transmits one bind packet per 8994 µs slot on hop channel 0 (+ the current `FOFS`), idx cycling 0, 5, …, 45 (one full cycle = 10 slots ≈ 90 ms):

`11 03 01 txid0 txid1 idx h[idx] h[idx+1] h[idx+2] h[idx+3] h[idx+4] 00 00 00 00 00 00 01` + CRC, entries ≥ 47 sent as 0.

BIND does **not** hop: it repeats the bind packet on a single fixed channel (hop channel 0 + `FOFS`, the first entry of this ESP's table) for at most 30 s (`BIND_TIMEOUT_MS`) or until `STOP`, at the requested power (default `pwr_max` when `pwr` is omitted; the TS host sends 40). It is a short, user-initiated pairing transmission, as the bind button of a stock FrSky transmitter is; it is not the hopping link, so the FHSS reasoning for `LINK` does not cover it. Use a low `pwr` and keep the receiver close.

`D8Link.bind(power, fofs)` sends `FOFS` (default `DEFAULT_FOFS_HZ`) before `BIND`, so the receiver tunes to the offset later links use rather than whatever an earlier link left in the firmware's RAM.

While binding, `STOP`/`U` ends it, `STAT` (bind=1), `PING`, `INFO` and `S` are answered as when idle, any other request gets `ERR busy binding` and the bind keeps running.

Receiver side (Betaflight `src/main/rx/cc2500_frsky_shared.c`): bind mode listens on channel 0 with address filter 0x03 (byte 1). Tuning sweeps FSCTRL0 −126…+126 in steps of 5 every 50 ms and keeps the first offset with a CRC-ok bind packet (byte 2 = 0x01) and LQI > 50 as `frsky_spi_offset`, so the receiver tunes itself to our carrier. Bind1 takes idx 0 (txid, h[0..4], rxNum = byte 12 = 0); Bind2 takes idx 5, 10, … strictly in order and ends at idx ≥ 45 at the first entry that is 0 or equals byte 17 → list length 47 for our tables (entry 47 = 0). `firmware/test/test_packet.c` runs a C port of getBind1/getBind2 on our frames (E8 identity + 200 generated ones, every start idx) and checks the recovered txid and hop list.

Reference TX (DIY-Multiprotocol-TX-Module, `Multiprotocol/FrSkyD_cc2500.ino`, `FrSkyDVX_common.ino`, checked Nov 2026): `FRSKYD_build_bind_packet` is the layout above with byte 17 = `rx_tx_addr[1]` (set to 1 for D8; the comment capture of a real FrSky TX `11 03 01 d7 2d 00 00 1e 3c 5b 78 00 00 00 00 00 00 01` is a unit-test vector); bind packets go out on channel 0 every 9000 µs with idx = ((state) mod 10)·5. Its D8 hop table is fixed (`(i·0x1e) mod 0xeb`, entry 47 = 1 as list end); its generic `Frsky_init_hop` steps `(ch + spacing) mod 0xeb`, bumps 0x00/0x5a/0xdc by one and zeroes entries > 46. We keep the mod-256 `d8_hop_table` (the E8 binding uses it) and enforce the same constraints by validation instead.

## Firmware version
`ver` in `INFO` is `<semver>+<hash8>`: `D8TX_FW_SEMVER` from `firmware/main/CMakeLists.txt` plus the first 8 hex digits of a SHA-256 over the firmware sources (`firmware/tools/fw_version.mjs` computes the same value), so it changes exactly when the firmware does. Firmware older than this field has no `ver`. Hosts parse `ver` (like `txid`) as text. The web app bundles a build (`make -C firmware web` → `apps/web/public/firmware/manifest.json`, `{chip, version, flash, files:[{name, offset, path, size, sha256}]}`) and offers an update when `ver` differs. It writes only bootloader (0x1000), partition table (0x8000) and app (0x10000), never erasing flash, so the NVS identity (0x9000) survives.

## Error mapping
`args` wrong argument count or malformed hex; `range` a value out of range or non-numeric; `busy` link or bind active; `keyed` radio is keyed; `unknown` unknown command; `long` line too long; `bench-only` command exists only in a `CONFIG_D8_BENCH` build.

## Legacy bench commands
`TONE`, `ALT`, `RETUNE`, `PKT`, `HOP`, `STICKS` still exist but are not part of the API, and only in `CONFIG_D8_BENCH` builds (a release build answers `ERR bench-only`; `HOP 0` stays in release). `pwr` stays optional (default `pwr_max`). They keep their old bare `ERR <why>` replies and `K,...` report lines. `HOP 0 <pwr> [timeout]` is the legacy twin of `LINK`. Changed vs. the earlier bench firmware: `PING` is `OK proto=1` (was `P,d8tone,1`), `STAT` is the v1 form (was `S,keyed=...`), boot line is `EV boot` (was `I,boot`), and the `I,ready` line is gone.

## Telemetry listen (experiment, off by default)
Bench-only extension for listening to Betaflight's FrSky D8 telemetry reply. The d8tx library uses it (see "Telemetry in the library"); with `TLM 0` (the boot default) `LINK` behaves exactly as above. Host: `tools/d8-tx-host/tlm_listen.py`.

| Command | Reply | Notes |
|---|---|---|
| `TLM <every> [cap_us] [gain] [dec] [same] [stream] [ack] [mark] [retry] [skip_us] [bits]` | `OK every=.. cap_us=.. gain=.. dec=.. same=.. stream=.. ack=.. mark=.. retry=.. n=<samples> gain_max=..` | idle only (else `ERR busy`); RAM only. every 0 = off, else 4..940 slots. cap_us 500..12000 (default 10000), gain -1 = hardware AGC or 0..127 manual code (default 40, clamped to the chip's max), dec 16/32/64 (default 32), same 0 = listen on the next hop channel (default), 1 = on the trigger channel. cap_us*16/dec ≤ 6000. stream 0 (default) = blocking int16 dump; 1 = int8 payload shipped in the background while LINK keeps sending. ack 0 (default) = firmware advances tid +1 per trigger; 1 = host acks with `TID`. mark 1 = ch8 is 1500 us on trigger packets, 1600 on re-triggers, 1000 otherwise (drone-side receipt check through MSP_RC). skip_us 0..6000 / bits 4|8 (stream=1 only): the first skip_us of the capture is not shipped; bits=4 ships mean-removed samples scaled to ±7, I in the low nibble and Q in the high nibble (header `bits=4`, `n` = shipped samples). retry 0..3 (stream=1 only): when the on-chip energy check sees no reply, drop the capture (`EV tlm_drop k=.. ch=.. tid=.. try=.. nb=.. fit=.. sl=.. rt=.. gap=.. pgap=..`) and repeat the request with the same tid at the next free slot |
| `TLMX <tail_bits> <settle_us> [all] [probe]` | `OK tail=.. settle=.. all=.. probe=..` | experiment knobs, RAM only: tail 0..32 alternating bits keyed after the CRC of trigger packets (all=1: every packet), settle 0..300 us wait between the trigger unkey and the listen retune, probe 1 = half way between triggers send one data packet with ch8 1400 us and leave the next slot silent (`EV probe k=.. ch=.. gap=.. pgap=..`) |
| `TID <0..31>` | idle: `OK tid=<n>`; during LINK: no reply | idle: first tid of the next LINK (default 0). During LINK: replaces the tid for the next trigger in either mode (with ack=0 the firmware keeps adding +1 per trigger from the new value, so the host normally sends `TID` only with ack=1). With ack=1: the host sends tid+1 if it decoded a reply echoing tid, else the same tid (Betaflight's re-request rule). The next trigger waits for it (at most 1 s, then repeats the same tid) |
| `TCAP <khz> [cap_us] [gain] [dec] [pwr]` | `EV tlm ...` + payload, then `OK` | one capture at khz (2404000..2478000) + FOFS, no link. pwr −1 (default) = no keying (receive-only, available in every build); 0..`pwr_max` = key one data packet (counter 0, current sticks) on that frequency first, then capture: exercises the same unkey→capture path. Keying is bench-only: a release build answers `ERR bench-only bench build required`. LO returns to 2412 MHz afterwards |

With `TLM every>0`, slot k of a `LINK` is a trigger when k ≥ every and k % every == 0 (use an every that is not a multiple of 47, e.g. 48, so triggers walk the hop table):
- The trigger packet has byte 3 = 2 (Betaflight replies when byte3 % 4 == 2) and byte 4 = telemetry id `tid` (0..31; ack=0: +1 per trigger; ack=1: set by the host with `TID`; starts at the idle `TID` value, default 0). All other packets keep byte 3 = 0 and byte 4 = the slot counter: Betaflight reads byte 4 only on trigger packets (it echoes it in the reply and acks hub data when it equals its expected id, last + 1), so data packets are accepted unchanged. With ack=0 a trigger the drone misses puts its hub ack id out of step for up to 32 triggers. With ack=1 the host advances only after a received reply, so it repeats a missed request and, starting out of step, walks into the drone's expected id within 32 received replies. Hub bytes only appear when the receiver has FEATURE_TELEMETRY on; with it off the hub count is always 0 (`tools/d8-tx-host/d8hub.py`).
- stream=1: with `TLM every>0`, slot k is a trigger when k ≥ the previous trigger + every and the previous capture has gone out (and, with ack=1, its `TID` arrived), instead of k % every == 0.
- Right after the trigger packet's last bit (same critical section) the radio is unkeyed, retuned to the listen channel (default: next table entry, because Betaflight calls `nextChannel(1)` before it transmits the reply ~1380 µs after the packet), the RX gain is set, and a 16 MS/s ring capture runs for cap_us, boxcar-decimated by dec on the CPU. Slot k+1 is never transmitted (the reply occupies it); after the capture the link resumes at the first future slot (≥ k+2) on the normal schedule, so a receiver keeps hopping in step (Betaflight waits up to 9 ms after starting its reply on k+1's channel, then moves to k+2's, ~0.6 ms before our k+2 packet). stream=0: slots that pass during the blocking dump are skipped (20 KB at dec 32 ≈ 0.22 s ≈ 24 slots; the receiver went into RX failsafe ~80% of the time with every=48). stream=1: no slot is skipped except k+1; the int8 conversion and the UART output run in the ~1.9 ms idle gaps between packets (≈9 KB at cap_us 9000 takes ≈27 slots), and no other text (status lines, `STAT` replies) is printed until it is out.
- Each capture is reported as one line followed by binary payload:
  `EV tlm k=<slot> ch=<listen channel> tid=<id> fs=<Hz> n=<samples> dec=<dec> turn_ns=<unkey start→capture start> run_us=<capture> g0=<gain idx first> g1=<gain idx last> lost=<pairs> bad=<sessions> late=<pairs> work=<cycles> units=<sessions> to=<0|1> bytes=<4n> crc=<crc32 hex>` then exactly `bytes` raw bytes (int16 little-endian I, Q interleaved, Q **not** negated: negate Q for RF = LO + f) then `\n`. stream=1 adds `bits=8 sh=<shift> try=<re-trigger index> nb=<reply blocks> fit=<blocks in window> sl=<slot late us> rt=<retune us> gap=<us> pgap=<us>` before `bytes=<2n>`: the payload is int8 I, Q (the int16 values arithmetically shifted right by sh so the peak fits). For `TCAP`: k=0, ch=<khz>, tid=1 if a packet was keyed first, else 0. crc32 = zlib.crc32 of the payload. This line is longer than the 95-char request limit; it is a device→host event.
- Only `S`, `TID`, `STOP`/`U` and `STAT` are handled while linked (`STAT` is dropped while a stream=1 capture is going out); `S` lines that arrive during a capture/dump are buffered and applied after it.

## Telemetry in the library
`D8Link.start(..., telemetry=True)` (default) sends `TID <next id>` and `TLM 12 9000 40 64 0 1 1 0 1 1000 4` (`protocol.TLM_RECIPE`: every 12 slots, dec 64, int4 payload from 1 ms on; older: every 48 slots,
9 ms capture, dec 32, gain 40, next hop channel, stream=1, ack=1, retry=1) before `LINK`, and sets FOFS to `DEFAULT_FOFS_HZ = 0` when no
`fofs_hz` is given. 0 is right for a receiver bound to this ESP over the air: bind tunes the receiver to our carrier (bench, Tinyhawk bound to the ESP:
94.9% of triggers answered at FOFS 0 against 72.9% at -75 kHz, `experiments/15-ota-bind/data/SUMMARY.md`). The old default -75000 only suited the cloned E8
binding, whose receiver offset was tuned to the E8's carrier; pass it explicitly when you clone an identity instead of binding. The firmware keeps the recipe (RAM) across LINKs, so no firmware change was needed; the library keeps the id sequence across
links so the drone's expected id stays locked. A firmware answering `ERR` to `TLM` leaves telemetry off and the link still starts; `telemetry=False`
sends `TLM 0` if a recipe was sent before.
- Reader thread: byte-oriented, so `EV tlm ... bytes=N` + N payload bytes + `\n` can be interleaved with `OK`/`EV` lines. Payloads go to a worker thread
  (crc32 check, int8 I/Q, vendored decoder `d8tx/demod.py`, carrier shift sweep -150..150 kHz with the last good shift first, ~5 ms/capture), which
  updates the state and writes `TID` (next id only after a reply echoed the sent id, else the same id; not after the link ended). `EV tlm_drop` and
  undecodable captures count as triggers without reply.
- `D8Link.telemetry()` returns the dict in `.ru/plans/telemetry-stack-contract.md`; extra key `hub.patched` is filled from the table below.
  `catch_rate` = replies/triggers over 10 s; `powered` = reply within 3 s; `link` = within 1 s.
- Reply frame (cc2500_frsky_d.c buildTelemetryFrame L117-148): `11 txid0 txid1 A1 A2 RSSI hubcount tid hub[0..9]`.
  **A1** = `(getBatteryVoltage()/5)&0xff`, battery voltage in 0.01 V (battery.c L505, voltage.h L44) -> 0.05 V/count, wraps at 12.75 V (a 4S reads low);
  `vbat_v` uses hub VFAS 0x39 (0.1 V) when seen within 3 s, else A1. `battery` "absent" below 2.0 V. **A2** = ADC_RSSI>>4 (raw).
  **RSSI byte** = `(uint8)rssiDbm`, `rssiDbm = v*18/32 + 65` (v<128) or `v*18/32 - 82` (v>=128) of the CC2500 RSSI register v
  (cc2500_common.c L62-69); the library inverts it and applies the datasheet conversion (`v/2-72` or `(v-256)/2-72`), so `rssi_dbm` is the drone's
  received power of our packets (bench bytes 66-80 -> about -67..-60 dBm). `rssi` stays the raw byte.
- Hub decoding: ACC 0x24-26 (`acc_mg`; stock truncates to whole g), COURSE_BP 0x14 (`heading_deg`, whole degrees), RPM 0x03, TEMP1 0x02, TEMP2 0x05,
  FUEL 0x04 (percent if capacity set, else mAh), CURRENT 0x28 (0.1 A), VFAS 0x39 (0.1 V) or 0x3A/0x3B ((BP + AP/10)*21/11). Identical consecutive
  10-byte chunks are dropped (the drone resends its last chunk while out of step with our ids).
- Armed (`armed`, `armed_source`): patched STATUS bit0 when present ("patched"); else the stock RPM field ("rpm"), frsky_hub.c L186-207: armed ->
  `rcCommand[THROTTLE]/5` (0, or 200..400, 0 at idle throttle with motor_stop), disarmed -> `batteryCapacity/5`. RPM outside {0}+[200,400] -> disarmed;
  otherwise the library learns the disarmed value from replies received >= 2 s after it started sending ch7 low (twice the same value): a different
  value means armed, the same value means disarmed unless it lies in the armed range, then `None`. Limits: with no baseline and RPM 0 or 200..400 it is
  `None`; an armed drone at idle throttle with motor_stop and capacity 0 also reads 0 (`None`); RPM older than 5 s -> `None`.
- Throughput: one reply carries at most 10 hub bytes and a trigger comes every ~0.43 s (about 23 B/s), and the drone builds a new hub cycle only after the
  previous one was fully sent, so slow-rate fields (gyro/attitude of the patched firmware) refresh every few seconds, not at their nominal rate.
  (Old firmware / 48-slot recipe. The FAST block below moves attitude and gyro out of the hub path.)

## Patched Betaflight hub fields

Source: `tools/betaflight-patch/patches/0001-frsky-hub-telemetry.patch` (Betaflight 4.2.11, MATEKF411RX). Same hub framing
as stock (`5E id lo hi`, int16 LE, 0x5E/0x5D byte-stuffed, one `5E` tail per cycle). All stock IDs keep their meaning
except ACC.

| ID | Name | Unit / encoding | Rate |
|---|---|---|---|
| 0x24-0x26 | ACC X/Y/Z | true milli-g, int16 (stock: whole g x 1000, truncated) | every 125 ms cycle |
| 0x46 | STATUS | bit0 armed, bit1 ANGLE, bit2 HORIZON, bit3 failsafe mode, bit4 arming disabled, bit5 acro (neither ANGLE nor HORIZON) | every cycle |
| 0x47 | ARMING_DISABLE | low 16 bits of Betaflight `armingDisableFlags` | every cycle |
| 0x40-0x42 | GYRO X/Y/Z | 0.1 deg/s, int16, clamped (filtered gyro, roll/pitch/yaw) | odd cycles (4 Hz) |
| 0x43-0x45 | ATT roll/pitch/yaw | deci-degrees, int16 (yaw 0..3599) | cycles with n%4==2 (2 Hz) |

Byte budget (4 B per frame, 1 B tail per cycle): stock about 132 B/s; patched about 270 B/s (ACC 96, STATUS+ARMING 64,
gyro 48, attitude 24, tails 8 = 240 B/s, plus 1 s group ~28 and clock ~2). Worst single cycle is 53 B (n%8==0 with the 5 s clock frame),
under the 64 B `serialBuffer` of `cc2500_frsky_d.c`; the optional fields never share a cycle with the 1 s group.
The receiver sends 10 hub bytes per D8 packet, so the link is not the limit. `d8hub.patched_state()` decodes these.

## FAST block (patch 0003, `tools/betaflight-patch/patches/0003-frsky-d-fast-block.patch`)

Reply frame stays `11 txid0 txid1 A1 A2 RSSI cnt tid payload[10]`. `cnt` = 0x8A (bit 7 set, `FAST_FLAG`) means the 10 payload bytes are a FAST
block, not hub bytes; otherwise `cnt` is the hub byte count (0..10) as before. The payload is one little-endian 80-bit integer, fields from bit 0:
roll s12 (bits 0-11, deci-deg), pitch s12 (12-23), yaw u12 (24-35, 0..3599), gyro x/y/z s14 (36-49 / 50-63 / 64-77, 0.25 deg/s, filtered gyro,
clamped +-8191), seq u2 (78-79, +1 per fast block). Decoder: `d8tx/telemetry.py` `parse_fast`; offline check `tools/betaflight-patch/check/fast_block_check.py`.

Scheduling (drone): every reply is fast except each `FAST_HUB_EVERY`-th (3) one, which is a hub reply (a hub slot with nothing pending is fast too).
Fast replies never load, send or consume hub bytes; the `telemetryIdExpected` ack of the previous hub bytes is evaluated on every reply. The host ack
rule is unchanged (next tid after a decoded reply that echoed the sent tid). Hub fields (ACC, STATUS, battery, ...) therefore get one third of replies;
hub ids 0x40-0x45 are still sent. Patch 0003 also contains the hub-timer-stall guard (unsigned time difference in `processFrSkyHubTelemetry`).

Host: `D8Link.telemetry()["fast"]` = `{attitude_deg [roll,pitch,yaw], gyro_dps [x,y,z], seq, age_ms, rate_hz}` (None until the first fast block;
`rate_hz` over a rolling window). The backend publishes the same dict as `radio.fast` in `/api/status`. Bench (default recipe, 8.5 replies/s):
fast 5.7 Hz (interval p50 0.12 s, p95 0.23 s), hub replies 2.85 Hz, seq gaps 0; see `experiments/13-fast-attitude-telemetry/data/e2e/`.
