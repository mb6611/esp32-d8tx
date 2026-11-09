# B3: Tinyhawk bound to the ESP over the air (2026-11-09)

Plan: `.ru/plans/d8-ota-bind.plan.md` unit B3. Owner present, props off, drone on USB power (no battery), arm disallowed in
every link (ch7 = 1000, firmware `armok=0`). `caffeinate -dimsu` ran for the session, and `pmset` showed no sleep inside the runs.

## Result
- **The bind works first try.** The drone took our identity within ~4 s of `bind_rx` and saved it to EEPROM itself (no `save`
  needed). The binding survives a reboot and works right away without a reboot.
- **After the bind, FOFS 0 is the right carrier offset.** At power 127, FOFS 0 got a 94.9% telemetry catch rate and
  FOFS −75 kHz got 72.9%. The −75 kHz workaround now costs packets.
- In every link, the RC readback over MSP_RC matched our sticks exactly, and RX failsafe never came back after lock.

## Identity (DevKit, firmware d8tx-v1 with B1 changes, flashed at 921600)
`ID` → `OK txid=6ff3 start=205 step=254` on first boot (random), and the same after reset (NVS). `INFO` has `txid=6ff3`. The firmware
prints txid in **lowercase** hex. `ID` accepts upper or lower case, and an invalid step gives `ERR range hop_table` (`id_case.log`).

## Bind (B3.2, `bind_run.py`, `bind_run.log`)
`BIND 30` at FOFS 0 on the ESP, then `bind_rx` in the drone CLI. 4 s later `get frsky_spi` showed:

| | before (E8) | after (ESP) |
|---|---|---|
| frsky_spi_tx_id | 66,178 | **111,243** (= 0x6f,0xf3) |
| frsky_spi_offset | −32 | **4** (second bind: 3) |
| frsky_spi_bind_hop_data | E8 table | 0,203,201,…,115,113,0,0,0 = `d8_hop_table(205, 254)` entries 0..46 (205+254·i mod 256), then 0s |

`diff_all_before.txt` → `diff_all_after_bind_noreboot.txt` / `diff_all_after_bind.txt` (after `exit` reboot) /
`diff_all_final.txt`: only those three lines changed. The RX code wrote EEPROM itself, so the values survive the CLI `exit` reboot.
The receiver offset moved by +36 steps (~ +57 kHz), the same size as the −50…−75 kHz FOFS shift we used to need with the E8 binding.

**No reboot is needed.** In the second bind, the offset was first set to a sentinel of −20 (not saved). Then I ran `bind_rx` and
**the TS core `D8Link.setFofs(0)` + `bind(127)` + `stopBind()`** (`hw-check.ts --bind 8`, `ts_bind.log`). The link that followed
got 90.9% catch while the FC was **still in the CLI**, never rebooted. The offset was re-tuned to 3 and persisted after reboot. With
CLI `bind_rx`, leaving the CLI with `exit` reboots the FC anyway. The RX LED was not observed (no camera on it).

## Links (B3.3, `node packages/core/scripts/hw-check.ts --seconds 60 --power P --fofs F`)
Telemetry was on (`TLM_RECIPE`). The FC was polled over MSP (RC + STATUS, 5 Hz) during the link. Sticks were
1100,1200,1300,1400,1450,1550,1000,1600. With `map TAER1234`, the expected MSP_RC is [1200,1300,1400,1100,1450,1550,1000,1600].

| power | FOFS | sender Hz | max gap ms | triggers | replies | catch | drone RSSI dBm | RC match | failsafe after lock | log |
|---|---|---|---|---|---|---|---|---|---|---|
| 127 | 0 | 111.18 | 14.2 | 534 | 507 | **0.949** | −67.6 | 238/238 | 0 | link_p127_fofs0.log |
| 127 | −75000 | 111.18 | 24.7 | 619 | 451 | 0.729 | −70.2 | 238/238 | 0 | link_p127_fofs-75000.log |
| 30 | 0 | 111.18 | 16.5 | 662 | 431 | 0.651 | −81.8 | 235/235 | 0 | link_p30_fofs0.log |
| 30 | −75000 | 111.18 | 16.2 | 702 | 371 | 0.528 | −86.2 | 239/239 | 0 | link_p30_fofs-75000.log |
| 127 | 0 (TS bind, FC in CLI) | 111.18 | 16.1 | 275 | 250 | 0.909 | −66.7 | – | – | ts_bind.log |

- In every run: `skipped=0`, 0 STAT timeouts, RC max diff 0 µs, RX lock 2.5–3.2 s after LINK, failsafe back on after STOP, never armed
  (arming_disable = THROTTLE during the link, because throttle was 1100).
- Earlier references: 97.8–99.3% at −75 kHz with the E8 binding at power 127 (`../telemetry/SUMMARY.md`). Power 30 sits near the
  receiver's sensitivity edge on this bench, so use 127 for comparisons.
- A first power-30 FOFS 0 run (log overwritten, with the old hw-check decoder) ended with `link_end why=err` at ~52 s. This is
  the known torn-UART-line case (memory d8tx-link-uart-limits). It did not repeat in the 5 later runs.

## TS core against the real firmware
`D8Link.info()` and `id()` parse `txid: '6ff3'` as text (it is not turned into a number) and set `link.txid = [111, 243]`. The worker
decoder (`src/worker/demod.ts`, which hw-check now uses) accepted replies with that txid. `bind()`/`stopBind()` work, and STAT shows
`bind=1` and then `bind=0`. `EV bind_end why=stop slots=891` came back for an 8 s bind.

The core needs no fix for parsing. Two behaviour points need attention (see the parent report):
1. `DEFAULT_FOFS_HZ = -75000` (`packages/core/src/protocol.ts:8`, used by `link.ts` start) is now the worse offset for a drone bound
   to the ESP. After binding, use 0, or the FOFS that was active during the bind.
2. `BIND` transmits at whatever FOFS the firmware holds in RAM. That can be left over from an earlier link: STAT showed
   `fofs=-75000` during a bind in this session. A bind at −75 kHz followed by links at 0 would mis-tune the receiver.
   `D8Link.bind()` should set FOFS first (to the same value the links use).

## Tinyhawk bind steps (for the UI instructions)
1. Props off. Connect the ESP in the app, with no link running.
2. Put the drone in bind mode, either with its bind button held at power-up, or over USB in the Betaflight CLI with `bind_rx`
   (Configurator CLI tab, or any serial terminal at 115200: send `#`, then `bind_rx`).
3. Click Bind in the app (FOFS 0). The drone binds within ~2–5 s: Betaflight sweeps the offset −126…+126 in steps of 5 every 50 ms
   and saves the result automatically.
4. Click Stop, or wait for the 30 s auto-stop. If you used the CLI, type `exit` (this reboots the FC; no `save` needed). The
   binding is already active before the reboot.
5. Check: `get frsky_spi` shows `frsky_spi_tx_id` = the app's txid as two decimal bytes (6ff3 → 111,243).

## Restoring the E8 binding (not done: the owner chose to keep the drone bound to the ESP)
In the drone's Betaflight CLI (values from `diff_all_before.txt`):
```
set frsky_spi_tx_id = 66,178
set frsky_spi_offset = -32
set frsky_spi_bind_hop_data = 0,57,112,167,222,21,76,131,186,241,40,95,150,205,4,59,114,169,224,23,78,133,188,243,42,97,152,207,6,61,116,171,226,25,80,135,190,245,44,99,154,209,8,63,118,173,228,0,0,0
save
```
Another way is to re-bind to the E8 with its bind procedure. To make the ESP clone the E8's identity instead, use `ID 42B2 2 55`.
The firmware accepts it (`OK txid=42b2 start=2 step=55`, `id_case.log`). It was set back to `ID 6ff3 205 254` right away.

## Files
`bfcli.py` (CLI helper; sends no `exit`/`save` unless asked), `esp.py` (raw protocol lines), `bind_run.py` (both-sides bind),
diff_all snapshots, run logs. hw-check changes: `packages/core/scripts/hw-check.ts`.
