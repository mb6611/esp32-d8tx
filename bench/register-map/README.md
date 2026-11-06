# Classic ESP32 RF register / function map (living document)

Target: ESP32-D0WD-V3 rev 3.0 (DevKit V1, 40 MHz XTAL). Created 2026-11-06 by offline synthesis. Later hardware additions include the **idle-only** register read (2026-11, never keyed, no writes; `idle-check/README.md`, folded into §4, §5, §9, §11). The keyed-state read (2026-11, `keyed-read/README.md`, raw `keyed-read/logs/run.txt`, independently checked) is also folded in; it covers only K0, ch1 2412, count 6143, two slots (PBUS 127 and 0).

Inputs (kept as audit trails; they hold the long form, raw-file paths and disassembly quotes):
- [`research/measured.md`](research/measured.md): what our runs measured. Cited below as **M§n**.
- [`research/vendor-tx.md`](research/vendor-tx.md): what ROM, libphy and librftest do, by disassembly. Cited as **V§n**.
- [`research/vendor-functions.md`](research/vendor-functions.md): deep vendor audit (BBPLL DIV_DAC, cbw40, SAR, txdump). Cited as **VF§n**.
- [`research/tx-path-search.md`](research/tx-path-search.md): offline TX-path search, DWARF checks, `wdev_mac_reg_store`. Cited as **T§n**.
- [`dac-clock-read/README.md`](dac-clock-read/README.md): idle BBPLL/`0x3ff00024` read (2026-11).
- EXT: [whstudio123/esp32-iq-tx `docs/REGISTERS.md`](https://github.com/whstudio123/esp32-iq-tx/blob/main/docs/REGISTERS.md). It is **ESP32-S3 and S31 only**, and says it is a snapshot of a verified path, not a full RF setup.

Bottom line: **we have not shown that DAC-to-RF playback works on the classic chip, and we have not shown that any single register blocks it.** The engine at `0x60033d98` runs, sequences addresses and completes. Whether it reads samples and drives the DAC is open. Four external CC2500 sessions saw LO/tone leakage only when we keyed the vendor tone path, and saw no sample-dependent RF, with the in-slice positive control missing or partial (M§3).

## Evidence classes

| Tag | Meaning |
|---|---|
| **MEASURED** | Read or observed on our board; a raw file backs it (see M§). |
| **BINARY-MAPPED** | From disassembly or source constants (ROM, libphy, IDF headers); nothing read from our board for that item. Behaviour is what the code does, not proof of RF effect. |
| **CROSS-CHIP HYPOTHESIS** | Translated from EXT or the S3 backend by offset or shape. Nothing on the classic chip confirms it. |
| **UNKNOWN** | No source says; or sources conflict. |

Addresses use the `0x6000xxxx` form; `0x3ff4xxxx` / `0x3ff7xxxx` are aliases (V§0).

## Hazards (read before any write)

| Tier | Action | Why |
|---|---|---|
| **HANG** | Write-1 to `0x60033d00/08/10/18/20` | RTC-WDT reset (M§4, M§7). txeng refuses these. |
| **KEYS / FORCES RF** | `rom_start_tx_tone_step`, `txcal_debuge_mode`, `force_txon_en`, `pbus_xpd_tx_on`, `set_txclk_en(1)`, any write to `0x600060a0[11:8]` | Radiates. Needs explicit user approval; first keyed burst after boot overran the 444 µs bench rule (M§7). See `playback-cc2500-check` memory. |
| **PLL RISK** | Writing `0x6000608c[27]` or BBPLL I2C (block 102/`0x66`, host 4) by copying the S3 `rom_dac_rate_set`; in particular BBPLL reg 11 also holds `DIV_CPU`/ENDIV5 bits | Can retune CPU/peripheral PLL (V§8, VF§9). Do not write without a plan; reads are fine (`dac-clock-read/`). |
| **HANG (SAR)** | Calling `rom_get_fm_sar_dout` / anything built on it (`rom_txtone_linear_pwr`, pwdet reads) | It polls `0x6000e050[26:24]==0` **with no timeout**; hangs if the SAR is not powered. `en_pwdet` first (a write). Not a pure read (VF§6). |
| **Unknown side effects** | Clearing `0x600060c4[18]`, writing `0x600050f0`, `0x60033dc0` | FE/MAC state; read first (V§8). Leave `0x6000880c[19:18]` alone (SAR power, not TX). |
| **Artefact** | CPU reads of an RF-owned bank return `0xa55aa55a`; analysing untouched words fakes a -625 kHz line; `0x60033db4` mask is a counter artefact | M§7 |

**Two kinds of experiment, never merged:**
- **No-RF observation**: pure register *reads* at idle, offline disassembly. Anything that writes PHY/FE state (e.g. `rx_mode()`) or writes playback control `0x60033d98` (engine run) is **not** pure read-only: classify it as an unkeyed write experiment, expected no radiation but not proven, and run it only with the user's say-so. Still needs a bench session.
- **Approved bench experiment**: anything that keys RF or writes FE/TX state. Requires explicit user approval each time, bounded and pre-registered (see Backlog).

## 1. Sample memory and bank ownership

| Address / field | Role | Status | Evidence |
|---|---|---|---|
| `0x3ffe8000..0x3fff7fff` | 64 KiB I/Q window (16384 words). Capture writes words `0..n-1`. Engine addresses the same range. | MEASURED | M§1; S2 `D follow_*` |
| same | `get_txdumpaddr` returns `0x3ffe8000` (and 12 as `plcp_11g_len`); `clear_txdumpmem` fills `0x5aa55aa5` over 16383 words. Both live in `crypto_common.c` next to `crypto_encap`; no vendor caller found (ROM checked by literal only). This shares the address with our window but most likely means a Wi-Fi MAC-frame dump for the crypto test (INFERENCE from names/context; nothing reads it back). It is **not evidence of a TX I/Q sample path**; the earlier "supports the window being TX sample memory" is withdrawn. Shared dump RAM only. | BINARY-MAPPED (addresses, fill); role INFERENCE | V§5, T§3, VF§5 |
| same | Word format capture: I `[9:0]`, Q `[19:10]`, Q negated. Format the engine *plays*: unverified. | MEASURED (capture) / UNKNOWN (play) | M§1 |
| same | Engine running alone writes nothing to the window. Engine *reads* are never shown. | MEASURED / UNKNOWN | M§1, M§3 |
| `0x3ff000a8[6:5]` `MAC_DUMP_MODE` | Bank owner. 0 none, 1 upper 32 KiB, 2 lower, 3 both (capture-side). | MEASURED (capture) | M§1 |
| same | Engine timing/completion identical under modes 0/1/2/3. Which mode the engine needs to *read* is unknown; bank-check at mode 2 and 1 saw no sample-dependent RF. | MEASURED (timing) / UNKNOWN (need) | M§1, M§6 |
| S3 analogue `0x600c101c[3:0]` 0/4 | CPU-idle / RF-playback ownership (EXT) | CROSS-CHIP HYPOTHESIS that classic uses mode 2/3 for playback | M§6 |

## 2. Capture block (RX side, for contrast)

| Address | Role | Status | Evidence |
|---|---|---|---|
| `0x60033d90` DUMP_CTRL | count `[13:0]`, bit15=40 MS/s, bit16=16 MS/s, none=80, bit17 ring, bit18 done RO, bit19 trigger pulse, `[23:20]` source, bit31 enable. RW mask `0x7ff3ffff`; bits 31/19 never written by census. | MEASURED (rates, ring) / BINARY-MAPPED (layout; librftest `adctrig`) | M§2, V§5 |
| `0x60033d94` | samples written `[14:0]`, RO; stays 0 while engine runs alone, so **not** an engine progress counter | MEASURED | M§2 |
| `0x60033dc4` | `mac_init` writes `0x03020100`; esp-sdr copies it. RW | MEASURED + BINARY-MAPPED | M§2, V§5 |
| `0x3ff5c02c` | RX gain force, bit23 + `[31:24]` | BINARY-MAPPED; forcing max changed nothing in loopback | M§2 |
| `0x600110f4[0]`, `0x6001c0b8[0]` | BT vs Wi-Fi capture-source mux (libbttestmode `bt_bb_dump`). Capture-side only; no TX-side mux found in vendor code. | BINARY-MAPPED | V§5 |

## 3. Candidate playback engine `0x60033d98` (= DUMP_CTRL + 8)

Reset 0, RW mask exactly `0x8ff8bfff` (MEASURED, two passes). **No classic vendor binary references `0x60033d98` or `0x3ff73d98`; classic `librftest` has capture `adctrig` but no `dactrig`** (V§1, V§5). The S3 has `dactrig` programming `0x60033d64`. Everything below about the classic engine is therefore our own reverse engineering, with no vendor recipe to compare against.

| Field | Behaviour | Status | Evidence |
|---|---|---|---|
| bit 31 | run. Done follows after time proportional to count, with TX powered down and any bank mode. | MEASURED | M§3 |
| bit 18 | done, RO; stays while run stays set; clears with run | MEASURED | M§3 |
| `[13:0]` | N = count+1 samples (1..16384); count 0 never completes | MEASURED | M§3 |
| bit 15 | 1 → 80.01 MS/s, 0 → 40.00 MS/s **engine completion time**. Says nothing about the DAC clock. | MEASURED (completion) / UNKNOWN (DAC) | M§3 |
| bit 19 | With run set: no done; clearing it → done. Behaves as hold gate **or** as loop; the data fit both. EXT/S3 vendor `dactrig` calls it **loop**. | MEASURED behaviour; role **UNKNOWN** (hold vs loop) | M§3, M§6, V§5 |
| `[27:20]` | Writable. 0x00/0xff/0x01/0x80 same timing. S3 vendor writes `count & 0xff` here; no keyed classic session ever set it. | MEASURED (writable, no timing effect); semantics CROSS-CHIP HYPOTHESIS | M§3, V§5 |
| retrigger | Run must be cleared first; no auto-restart. Seam of MCU rearm loop 0.49–0.59 µs. | MEASURED | M§3 |
| memory access | Sequences addresses `0x3ffe8000+4·[0..N-1]` at the engine rate (seen by a concurrent capture). Data read not shown. | MEASURED (addresses) / UNKNOWN (data) | M§3 |
| radiation | Keyed LO/tone leakage seen at 2412 by CC2500. Sample-dependent RF: **neither shown nor excluded** (±1.25 MHz pattern out of slice, DC, ±156 kHz, bank 2 vs 1). On-chip self-loopback is blind. | MEASURED; conclusion UNRESOLVED | M§3, `bench/cc2500-rxdiag/playback-check/` |

### Vendor absence of `dactrig` vs confirmed timing: how to read them together
Timing, completion, address sequencing and rate-bit effects on the engine **are measured** and repeatable. That proves the engine state machine exists and runs. It does **not** prove the DAC is fed, because (a) no vendor classic routine exercises it, so no known-good recipe or prerequisites (DAC rate, source mux, NCO and force state) are available to copy, and (b) the S3 recipe contains steps the classic chip may not have (`rom_dac_rate_set`; V§6). Absence of vendor evidence is not evidence of a hardware limitation either.

## 4. Tone / NCO registers (FE block `0x60006000`)

Three registers; bit 18 of each is a tone enable, `[17:10]` a gain field stored **negated** (gain 127 → `0x81`), low bits frequency. **Source: `rom_stop_tx_tone(n)` clears bit 18 of b8 for n=1, bc for n=2, c4 for n=3, and all three for other n including 0** (V§3).

| Register | S3 homolog (offset match) | What our code does | Status |
|---|---|---|---|
| `0x600060b8` tone 1 | `0x60006040` | `rom_start_tx_tone_step(1,0,127,…)` sets bit 18 and gain; txeng flag 8 / `clr18` then **clears bit 18**. Idle read `0x2003a020` (bit 29 set, bit 18 clear; MEASURED idle); keyed `0x20060400`; after clr, immediately after RUN and at DONE `0x20020400`; after unkey `0x20000000` (keyed-read, PBUS 127 and 0). | MEASURED (218 keyed lines, 159 cleared, PB logs) + BINARY-MAPPED (encoding) |
| `0x600060bc` tone 2 | `0x60006044` | **Implicitly forced off on every key**, as `start_tx_tone_step` writes bc with `en2=0`, and unkey writes zeros to b8 and bc. **Idle read = 0 (MEASURED idle, bit 18 clear).** **Keyed readback = 0 in all five phases (after key, after clr18, immediately after RUN, at DONE, after unkey; K0, ch1, 2 slots).** | BINARY-MAPPED (keyed behaviour); keyed MEASURED = 0 in tested mode; idle MEASURED |
| `0x600060c4` tone 3 | `0x6000604c` | **Never written by txeng, `wifiscwout` or any classic vendor tone start. Only referenced by `rom_stop_tx_tone`. Read at idle and during the tested keyed bursts: `0x00000000`, bit 18 clear (MEASURED in both conditions).** Nothing on our chip shows it is a TX tone. | BINARY-MAPPED (existence); homology CROSS-CHIP HYPOTHESIS; idle MEASURED = 0; **keyed MEASURED = 0 in all five phases (K0, ch1, 2 slots)** |

Correction carried from the audits: earlier text said "txeng only clears b8". Precisely: b8 is cleared explicitly (flag 8), bc is off implicitly by the key call, c4 is untouched; idle and keyed reads (tested mode only) show bc=0 and c4=0 in every phase.

What follows for us: EXT notes that on the S3 an NCO left on blocks IQ TX. By the same shape, a set `c4[18]` (or any NCO) is a **candidate** mask on the classic chip. c4 reads 0 at idle and in all five keyed phases of the tested mode (K0, ch1 2412, count 6143, PBUS 127 and 0), so c4[18] is not set there and a c4 NCO mask is not indicated in that mode. Other modes (`K 1`/`K 2`) and channels are unread. **Do not state that c4 blocks playback**, and do not infer that the RF DAC is wired.

`0x600050a8[3:0]`: fine tone bits, used when b8 bit 29 is set (our boot state): `f&3` → `[1:0]`, `f2&3` → `[3:2]` (BINARY-MAPPED). Tone-frequency unit (f ≈ 156.25 kHz/LSB, or 39.06 kHz in fine mode) is **inferred**, not shown (V§3).

## 5. RF chain force / clock fields (`0x600060a0` and neighbours)

| Address / bits | Role from code | Status | Touched by txeng? |
|---|---|---|---|
| `0x600060a0[17:16]` | TX clock enable (`rom_set_txclk_en`; vendor CW sets 3) | BINARY-MAPPED | `K 0`: set via `txcal_debuge_mode`. `K 1`/`K 2`: **not set** (V§4). Idle read: 0 (MEASURED idle); keyed (K0, ch1): `4103c000` after key, after clr18, immediately after RUN and at DONE, `0100c000` after unkey; low16 `c000` unchanged, only upper bits change at unkey, meaning not established. |
| `0x600060a0[15:14]` | RX clock enable | BINARY-MAPPED; idle read = 3 (MEASURED idle) | not directly |
| `0x600060a0[26:25]` | PBUS force mode (`rom_pbus_force_mode`) | BINARY-MAPPED; idle read = 0 (MEASURED idle) | `K 0` via debugmode; not `K 1`/`K 2` |
| `0x600060a0[9:8]`, `[11:10]`, `[11:8]` | TX-force sequences (`force_txon_en`, `phy_close_pa`, `fcc_bt_force_tx_tone` writes `0xe`). Carrier by forcing TX, not by NCO. **Forces RF.** | BINARY-MAPPED; S31 `0x20100890[11:8]` link is CROSS-CHIP HYPOTHESIS; idle `[11:8]`=0 (MEASURED idle, no TX force); keyed `[11:8]`=0 (low16 `c000`, tested mode) | no |
| `0x600060a0[31]` | PBUS busy (read) | BINARY-MAPPED | n/a |
| `0x60006094` | PBUS row/col/value command word (`row<<2 \| col<<15 \| val<<6 \| 2`) | BINARY-MAPPED | via ROM calls |
| `0x60006000` | Idle value `0x01bb8040` (MEASURED idle). Role **UNVERIFIED**. A "digital gain" label came only from another agent's unverified audit; `research/vendor-tx.md` does not verify it. Do not rely on it. | value MEASURED idle; role UNVERIFIED | no |
| `0x60006004` | Read by `wifiscwout` to compute tone gain: `max(backoff+43-REG, 0)`. Our fixed 127 differs from that. | BINARY-MAPPED; idle value `0x02081018` (MEASURED idle, meaning not decoded) | idle read only |
| PBUS (4,1), (5,1) | Set to 127 / pwr during key; (5,1)=127 while keyed, 0 before/after. Scale unknown. | MEASURED | yes |
| `0x6000880c[19:18]` | `SENS_FORCE_XPD_SAR`: SAR/power-detector power, not TX | BINARY-MAPPED | no. Do not write. |

### FE2 TX interpolator hint
`0x600050f0` = `FE2_TX_INTERP_CTRL` (IDF `fe_reg.h`): bit 10 `FE2_TX_INF_FORCE_PU`, bit 9 `_PD`, `[8:0]` timing set by libphy `tx_delay_cfg` (240 or 100) and ROM `phy_freq_correct`. By name this is the stage before the DAC. Vendor code powers and times it but **no vendor code selects its input** (V§6). Hint only: if it is forced down in RX mode, a keyed playback might not reach the DAC. **Status: BINARY-MAPPED by name. Idle read (MEASURED idle): `0x464` = PU set, PD clear, `[8:0]`=0x64, so it is not forced down at idle. Keyed value MEASURED `0x464` in all five phases (K0, ch1, PBUS 127 and 0), so PU stays set and PD clear while keyed and running in that mode; role as a blocker still UNKNOWN, other modes unread.** `0x600050dc` (TX IQ, FE2) is named only; idle value `0xd95e1f43` (MEASURED idle), meaning unknown; keyed value unread.

## 6. Rate and DAC clock

| Item | Status |
|---|---|
| Classic ROM has no `rom_dac_rate_set` function, and no classic binary writes `0x6000608c` (S3 writes `0x6000608c[27]` plus BBPLL I2C blocks 102/103). | BINARY-MAPPED (absence of the function/writer); the earlier constant-argument I2C scan missed batched writes, see next rows (VF§0.4). |
| `0x6000608c` idle value `0x00000000` (MEASURED idle; never written by any classic binary) | MEASURED idle |
| Classic BBPLL I2C block 102, host 4, reg 11 bit 0 `I2C_BBPLL_DIV_DAC` (same field name as S3 `rom_dac_rate_set`'s divider). IDF clock init writes reg 11 whole (`0x43`/`0xc3`, bit0=1); libphy `phy_i2c_init` then does `reg11 &= 0xfe` (DIV_DAC=0) in a batched I2C write. A later clock PLL reconfig (`rtc_clk_cpu_freq_set_config`) can change reg 11 again. | BINARY-MAPPED for the write (VF§1.1, VF§2); the field's role as the physical DAC clock is an S3-based name-match HYPOTHESIS |
| **Corrected:** the earlier "no classic DAC-rate equivalent found" is now "**field found, no classic `rom_dac_rate_set`-style function**" (V§1.4/V§6 hold only for a named routine). | BINARY-MAPPED |
| Live idle read (2026-11, two identical passes after reset, read-only `I` command, no I2C writes/key/engine): BBPLL reg10 = `0x10` (`[5:4]`=1 as predicted), reg11 = `0xc2` (the IDF value `0xc3` with bit 0 cleared, i.e. the libphy `&= 0xfe`) so DIV_DAC (bit0) = 0; `DPORT_WIFI_BB_CFG` `0x3ff00024` = `0x10000002` (bit1 set, bit2/3 clear, bit28 set). Reg 11 bit 1 was already set in the IDF `0xc3` value, so it is not evidence for or against a later PLL retune. Evidence `dac-clock-read/README.md`, `dac-clock-read/log.txt`. **Idle only.** | MEASURED idle |
| Keyed state of reg 10/11 and `0x3ff00024`; whether the physical DAC follows DIV_DAC; whether DIV_DAC=0 already equals S3 "rate 0" (S3 rate 0 = DIV_DAC 0 plus bit15=1, consistent with our bit 15 = 1 but not proof). | **UNKNOWN** (not measured; HYPOTHESIS VF§1.2) |
| `0x3ff00024` bit 2 / bit 3: classic `ram_bb_bss_cbw40_dig` clears bit 3 and sets bit 2 = `en&1` (cbw40 bandwidth path); `ram_bb_bss_bw_40_en` also sets bit 2. Similar S3 write targets a separate register from `dac_rate_set`. Bit 1 is written by `mac_enable_bb`/`phy_close_rf`/`crypto_encap`; bit 28 by `mac_enable_bb`; bit 0 by `phy_wifi_bb_reset`. Idle: bit 2 clear and bit 3 clear. Active `cbw40` state would be bit 2 set, bit 3 clear (not read keyed). Roles beyond "bandwidth-related, name level" are unknown; it is only a second DAC/BB-clock *candidate*. | BINARY-MAPPED (writes); role NAME-ONLY / HYPOTHESIS (VF§1.4, VF§2) |
| `0x60033d98[15]` changes engine completion time only | MEASURED |
| EXT: S3 `[15]` is "together with the ROM clock setting" | CROSS-CHIP HYPOTHESIS that the classic chip needs more than bit 15 |

## 7. Keying path (how RF has ever been seen)

| Mode | Steps | Result | Status |
|---|---|---|---|
| `K 0` | `txcal_debuge_mode(0)` + `rom_start_tx_tone_step(1,0,127,0,0,0)` + PBUS (5,1)=pwr | LO/tone leak seen externally at 2412 in every session; on-chip RX deaf | MEASURED |
| `K 1` | `rom_pbus_xpd_tx_on(pwr,288)` + tone; skips PBUS debug force, TX clock `[17:16]`, DCO set, `en_pwdet` | RX alive; **not even the tone detected externally (0/6)** | MEASURED; "because steps were skipped" is HYPOTHESIS (V§4) |
| Unkey | `g_phyFuns[68/4](0,…)`, `[0x124/4]`, `rom_stop_tx_tone(1)`, RX-only PBUS | State verified fine afterwards | MEASURED |
| Channel `Q` | `set_chanfreq`, cap-code, `rom_set_rf_freq_offset`; `cap_reg` 0xb0→0x30. No PLL-lock readback. | Only proves the path ran | MEASURED (weak) |

Source selectors: no TX-side data-source mux or TX IQ sample entry point exists in classic vendor code (T§4, T§5); the only muxes are capture-side. TX IQ/DC cal, `tx_cont_*`, `rom_loopback_mode_en` and `dac_out` (GPIO25/26 pad DAC, a name trap) inject no samples. The TX data path is therefore not inferred, and keyed behaviour remains the only test.

Implication: a `K 1` "no RF" null says little about playback; keying itself was silent. Libphy overrides some ROM slots (e.g. `txcal_work_mode`, `xpd_tx_on`; V§2): unkey runs libphy's `txcal_work_mode`, assuming `register_chipv7_phy` ran (not checked at run time).

## 8. Other registers `0x60033d00..0x60033dff`

Full census (reset, RW mask, 2 passes) is in M§4. Role-relevant summary:

| Registers | Summary | Status |
|---|---|---|
| `d00,d08,d10,d18,d20` (+ pairs `d04…d24`) | Write-1 hangs. By name (`ConfAddrGet`, `Plcp0AddrGet`, `BackOffCountGet`, `fill_tx_frame`) MAC TX descriptor/PLCP slots. | MEASURED hang; role BINARY-MAPPED (name level) |
| `dc0` ("candidate #2") | Ten values, no engine effect. Vendor `crypto_encap` writes `0x8000ffff`/`0x80007fff` around `tx_a_frame()`: MAC frame test plumbing. | MEASURED null; role BINARY-MAPPED |
| `dbc, dc8, dcc` | writable; no engine effect (few values tried) | MEASURED (low n) |
| `d80..d8c, dd0, dd4` | RO live counters; unchanged across an engine run | MEASURED |
| `db4` | Free-running; bits `[11:8]` not engine progress | MEASURED |
| remaining | masks in M§4 | MEASURED |

The range is the Wi-Fi MAC/BB aperture (alias `0x3ff73xxx`); read side effects are indistinguishable from counters.

**Vendor writes into this range (T§2).** libpp `wdev_mac_reg_store`/`_load` (called via `pm_mac_sleep`/`pm_mac_wakeup`) bulk-copy the `0x3ff73c00` bank (120 words), rewriting every word including `d98`, `d90`, `dc0`, `dc4` and the hang-prone `d00..d20`. It restores prior values; it never configures playback, and whether it runs in our image is unverified. So "no vendor code touches `d98`" is corrected to "no vendor code *programs* it".

**`dc0` and txdump:** `crypto_encap` writes `0x3ff00024`=2, `dc0`=`0x8000ffff`/`0x80007fff`, calls `tx_a_frame()`, then `dc0`=0. `get_txdumpaddr`/`clear_txdumpmem` share `0x3ffe8000` with our window but most likely dump Wi-Fi frame bytes (inference, T§3); that says nothing about the DAC, and a keyed dump could not separate playback input from output because they would share the same RAM.

## 9. S3 / S31 to classic translation

| Role | S3/S31 (EXT) | Classic | Classification |
|---|---|---|---|
| Sample buffer | `0x3fcd0000`, packed IQ10 | `0x3ffe8000`, 64 KiB | address MEASURED; play format UNKNOWN |
| Bank owner | `0x600c101c[3:0]` 0/4 | `0x3ff000a8[6:5]` | capture MEASURED; playback need UNKNOWN |
| Play control | `0x60033d64`, `[27:20]`=count low 8, bit19 loop, bit31 en | `0x60033d98`, same mask | offset/mask MEASURED; `[27:20]` and loop reading are CROSS-CHIP HYPOTHESIS |
| Rate | bit15 + `rom_dac_rate_set` (`DIV_DAC` reg 4 bit 4, `0x6000608c[27]`, block 103) | bit15; no ROM routine; BBPLL reg 11 bit0 `DIV_DAC` found, idle 0 (MEASURED idle) | UNKNOWN whether the DAC follows it |
| Capture off during TX | `0x60033d5c = 0` | `0x60033d90 = 0` | state observed idle (`0x60033d90`=0 in all logged snapshots and in B1a part 2); causal role never varied |
| NCO off | `0x60006040/44/4c[18]` | `b8/bc/c4[18]` | b8, bc, c4 all MEASURED idle (bit 18 clear; bc/c4 = 0); keyed bc/c4 = 0 in all five phases (K0, ch1) |
| TX force / clock release | after tone: release force, PBUS TX/RX off, clocks off | `0x600060a0` fields | BINARY-MAPPED; idle TX clk 0, RX clk 3, force fields 0; keyed (K0, ch1) low16 `c000` unchanged |
| Loop / periodic | S3 bit19; S31 bit19 + REGDMA/ETM timers | UNKNOWN | S31 REGDMA/ETM chain (`LP_SYS`, GPTimer) has no classic counterpart identified |

## 10. Conflicts resolved conservatively

| Claim A | Claim B | Handling here |
|---|---|---|
| "txeng only clears b8" (M§5) | bc is written off by code on every key (V§1); later keyed readback was 0 in the tested mode | Both true: b8 explicit, bc off by code (idle 0, keyed 0 in tested mode), c4 untouched (idle 0, keyed 0 in tested mode). |
| Bit 19 = hold (M§3) | bit 19 = loop (EXT, V§5) | Both fit the data. Listed UNKNOWN; T1/B6 discriminates. |
| Engine measured and rate-bit works (M§3) | no vendor code uses it (V§1) | Completion timing is measured; DAC feeding is not. No claim of working playback. |
| "RF keyed but no sample-dependent RF" | "playback null" | A null with a missing positive control (out of slice) is unresolved, not a negative. |

## 11. Prioritized test backlog

**Idle readback (2026-11, two identical passes, never keyed, no writes):** `b8=0x2003a020`, `bc=0`, `c4=0` (bit18 clear in all three); `a0=0x0100c000` (TX clock `[17:16]`=0, RX clock `[15:14]`=3, force fields 0); FE2 `50f0=0x464` (PU bit10 set, PD clear); `50a8=0`; `50dc=0xd95e1f43`; `6004=0x02081018`; `6000=0x01bb8040` (role still UNVERIFIED); `608c=0`. Details: `idle-check/README.md`, raw log `idle-check/logs/idle_read.log`. This is the **idle** state only.

**Idle readback part 2 (2026-11, two identical passes, after reset, no keys/writes/engine):** `0x600060c0=0x81` (role UNKNOWN; bit18 clear); `0x6000880c=0x002c000a` (`[19:18]`=0b11, SAR power field per binary map, no causal claim); DPORT `0x3ff000a8=0` (MAC_DUMP_MODE `[6:5]`=0); DUMP_CTRL `0x60033d90=0`; TXE `0x60033d98=0`. Raw log `idle-check-2/logs/idle_read.log`, summary `idle-check-2/README.md`. Idle only; says nothing about keyed or engine-running state.

**Keyed readback (2026-11, B2b narrow, two slots):** `T 0x97ff 1 100 140 3 {127,0}`, K0, ch1 2412, count 6143, flags KEY|CLR18|KREAD. b8: phase0 (after key) `20060400` (bit18 ON); after clr18, immediately after RUN and at DONE `20020400` (bit18 OFF); after unkey `20000000`. bc and c4 = 0 in all five phases. a0: `4103c000` through key/clr18/RUN/DONE, `0100c000` after unkey (low16 `c000` unchanged). 50f0 `0x464` in all phases. PBUS127 keyed 371 us, PBUS0 162 us. Raw: `keyed-read/logs/run.txt`, summary `keyed-read/README.md`; independently checked. Scope limit: this is one mode/channel/count; it says nothing on other modes or channels and does not show the RF DAC is wired. Reads were taken at the listed phases only, not continuously. The five B1a addresses unread here were read later at idle (see idle readback part 2).

Order is by information per risk. No item here is promised to settle its question; a clean read leaves the S3-based DAC-clock hypothesis unproven. **B1a and B2a are pure idle reads (no RF, no writes).** B1b, B2b, B3b write PHY or playback state: unkeyed write experiments, no radiation expected, user approval required. B4 is offline. B5+ need user approval.

| # | Test | Class | Settles |
|---|---|---|---|
| B1a | **COMPLETE at idle (2026-11; ten reads in `idle-check/`, remaining five in `idle-check-2/`; idle only, no keyed or engine-running implications).** **Pure idle read**, firmware as booted, nothing keyed, no capture, no writes: read `0x600060b8, bc, c0, c4, 0x600050a8, 0x600060a0, 0x60006000, 0x60006004, 0x600050f0, 0x600050dc, 0x6000608c, 0x6000880c, 0x3ff000a8, 0x60033d90, 0x60033d98`. Needs a txeng build with read access and no writes. | No-RF, read-only | c4 state, FE2 interp PU/PD, TX clock/force fields at idle; `0x60006000` value (role UNVERIFIED) |
| B1b | Same reads after `rx_mode()`. `rx_mode()` writes PHY state, so this is **not read-only**. | Unkeyed PHY-write; user approval | state change from RX mode |
| B2a | **Covered:** idle c4=0, bit18 clear. Read `0x600060c4` at idle (B1a). | No-RF, read-only | whether c4[18] is set at boot |
| B2b | **DONE for the narrow tested conditions (K0, ch1 2412, count 6143, 2 slots, five phases): c4=0 throughout.** Read `0x600060c4` after a key/unkey cycle. Keying radiates (see Hazards). Other modes/channels not covered. | Approved bench (keyed RF; done) | c4[18] not set in tested mode |
| B3a | **Covered:** idle 50f0=0x464, PU set, PD clear. Read `0x600050f0` at idle (in B1a). | No-RF, read-only | interpolator PU/PD hint |
| B3b | Read `0x600050f0` with engine running unkeyed. Running the engine requires writing `0x60033d98`. | **Not no-RF-read-only**: unkeyed write experiment, user approval | interpolator PU/PD while engine active |
| B4 | **Largely done** (VF§1, T§1–5): field found (`DIV_DAC`), no named routine, no TX source selector, no TX-side `MAC_DUMP_MODE` writer. Remaining offline: `pm_mac_sleep` caller gating in our image; `run_rftest_case` command table (any `adctrig` call with a fixed `trigcase`); `rom_spur_reg_write_one_tone`; last 4-entry batch at `phy_i2c_init` +0x2ed (only partly decoded). | Offline | Remaining gaps only |
| B4a | **DONE idle (2026-11):** BBPLL reg10/11 and `0x3ff00024`; result in §6. | No-RF, read-only (done) | DIV_DAC idle state |
| B4b | Idle reads still open: `0x60033dc0`; `0x60006030..0x60006044` (PBUS sequence index); raw `REG_READ` only of a SAR-related address, and only if SAR power is confirmed by other evidence (`0x6000880c` idle bits do not prove SAR is powered). Do not call `rom_get_fm_sar_dout` or `rom_txtone_linear_pwr`: they trigger and poll with no timeout and can hang. All no-write, no key. Keyed re-read of reg 10/11, `0x3ff00024`, `a0` in the same modes as B2b is the next low-risk keyed step (needs approval). | No-RF read / approved bench | Whether keying changes DIV_DAC or BB_CFG |
| B4c | Not read-only, approval needed, prioritised after B5: split in two. **B4c-1 (unkeyed write experiment, approval needed):** set `DPORT_WIFI_BB_CFG` bit 2 (active) with bit 3 clear (the `cbw40` state), or change BBPLL reg 11 `DIV_DAC`; the latter shares a byte with `DIV_CPU`, risk of retuning the CPU PLL. **B4c-2 (keyed power-detector test, separate explicit approval, TX-powered):** `en_pwdet` + SAR read (VF§6), the only on-chip observable that could tell DAC-to-RF from none; hang-prone, keyed backlog only, never bundled with B4c-1. | B4c-1 unkeyed write; B4c-2 keyed, separately approved | Whether DAC clock role or DAC-to-RF exists |
| B5 | **Only after B1a results and explicit user approval:** one bounded, pre-registered in-slice control. Pre-register in writing before the run: receiver centre/BW, slice, count/N, rate bit, bank mode, key mode (`K 0`), burst budget (stop on first overrun of the 444 µs rule), and decision rule. Run **pattern** (a tone placed inside the receiver's slice, e.g. +50 kHz close-in, with an in-slice positive control) vs **zero fill** at identical settings. Differences in slice power, not out-of-slice lines, are the evidence. | Approved bench | sample-dependent RF; playback word format |
| B6 | With B5's receiver: bit 19 set vs clear (hold vs loop); concurrent capture on sentinel window, no keying, can first test hold/loop without RF (M§8 T1). | T1 no-RF; B5-class for RF | bit 19 |
| B7 | `[27:20]` = low 8 count bits vs 0 under B5. | Approved bench | duplicate-count semantics |
| B8 | Bank mode 2 vs 1 vs 3 with only the lower bank filled, under B5. | Approved bench | bank need |
| B9 | **Not indicated in the tested mode (B2b read c4=0 in all keyed phases).** Would apply only if a keyed read in another mode/channel shows c4[18]=1: controlled clear-and-compare of c4 under B5. | Approved bench | causality of an NCO mask. The tested keyed zero argues against a c4 mask in that mode only. |
| B10 | Reproduce `wifiscwout`-style vendor CW (`txcal_debuge_mode`, `set_txclk_en`) vs `K 1` to test the skipped-steps hypothesis. | Approved bench | `K 1` silence |
| B11 | `Q` retune actually moves LO (external or lock readback). | Approved bench | channel-select row |

Rules for every approved run: only the user approves keying; stop on first overrun; do not repeat a failed key; use neutral wording in agent goals (`bench-agent-wording` memory).

## 12. Updating this map after an experiment

1. Put the raw files (log, jsonl, csv) in the experiment's own directory and record the path.
2. Find the row(s) the result touches (use the Backlog `#` and the sections above). Edit the row in place: new status, one-line fact, evidence pointer `path:line`.
3. Status rules: a status moves to **MEASURED** only with a raw file from our board; a null result counts only if its positive control passed in the same session. Otherwise keep **UNKNOWN** and note the control that failed. Never promote BINARY-MAPPED or CROSS-CHIP rows on reasoning alone.
4. If a result contradicts a row, don't delete it: add a line to §10 with both claims and the resolution.
5. Strike the backlog row (move to a "Done" note with the date and result) and add any new test it suggested.
6. New hazards go in the Hazards table immediately, with the incident and date.
7. Add substantial raw findings to `research/measured.md` (audit trail) with its evidence-tag convention; leave `research/vendor-tx.md` for disassembly changes. Edit `.ru` memories only via the user-memory process, separate from this file.

Last synthesis: 2026-11-06; deep vendor audit (`research/vendor-functions.md` = VF§, `research/tx-path-search.md` = T§) and idle DAC-divider read (`dac-clock-read/`) folded in later. Source paths marked `auto-drone/` in M§ are outside this repo.
