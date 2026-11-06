# Classic ESP32 vendor functions behind the S3 `dactrig` sub-steps (offline audit)

Offline and read-only: no hardware, no RF, no firmware changes. Written 2026-11-06. This file
continues [`vendor-tx.md`](vendor-tx.md) (cited as V§n) and does not repeat it. Inputs are the same
pinned binaries listed in V§0 (`libphy.a` `c2521071…`, `librftest.a` `17cdfede…`,
`libbttestmode.a` `fd512e31…`, `librtc.a` `e3411aee…`, ROM `esp32_rev300_rom.elf`), plus
`esp_wifi/lib/esp32/libpp.a` (only for §7) and the S3 ROM and libraries for comparison.

## Evidence classes used here
- **VERIFIED-BINARY**: read from the disassembly. The exact instructions or call arguments are quoted.
- **NAME-ONLY**: the role comes from a symbol, DWARF or IDF header name. The code does not show it.
- **HYPOTHESIS**: an inference that no binary or run has shown yet.

## 0. Method (reproducible)
1. `xtensa-esp-elf-ar x` each library. macOS `ar` cannot read these GNU archives. Then run
   `objdump -dr` on every object. For the ROM, run `objdump -d --start-address=0x40002f00
   --stop-address=0x40006800`.
2. The ROM `g_phyFuns` slot table is read from `.data_phyrom` at file offset `0x6e830`. The first
   word is the pointer, so the table starts at word 1. libphy's overrides are decoded from
   `phy_get_romfunc_addr`: an `l32r aX,(R_XTENSA_32 ram_*)` followed by `s32i aX,a10,<slot>`.
   The full override list matches V§2. It adds `0x030 ram_set_pbus_mem`, `0x034
   ram_write_gain_mem`, `0x050/0x070/0x074` cbw40 functions, `0x118 ram_txdc_cal_v70`,
   `0x12c/0x130` SAR reads, `0x144..0x150` IQ estimate and DCO cal.
   `0x044 start_tx_tone_step`, `0x04c stop_tx_tone`, `0x028 loopback_mode_en`, `0x0dc
   set_dco` and `0x128 txiq_set_reg` stay ROM.
3. A call-graph pass resolves `l32r a,(g_phyFuns); l32i a,a,0; l32i a,a,<slot>; callx8`. In ROM the
   literal is `0x3ffae0c0`. It also records constant `movi`s into a10..a15 before each call.
   I2C call sites are read as `(block, host, reg, msb, lsb, data)`.
4. **A blind spot the earlier scan (V§6) had:** libphy also writes analog I2C in *batches*,
   through `i2c_write_master(blocks[], hosts[], regs[], data[], n)` (`phy_chip_v7_ana.o` +0xba0).
   It writes `block | 1<<24 | reg<<8 | data<<16` to `0x3ff4e000 + host*4` and polls bit 25. The
   arrays are byte stores onto the stack, so a constant-argument scan never sees them. I decoded
   every batch in `phy_i2c_init` with a small register/stack emulator over its linear code. It is the
   only caller.

I2C block numbers: 98 RFPLL (host 1), 99 (host 0, SDM), 100 (host 0, RX), 102 `I2C_BBPLL`
(host 4, IDF `regi2c_bbpll.h`), 103 (host 1, "bbtop" by libphy names), 104 (host 3, "xtal"),
106 (host 2, "bias"), 107 (host 2, "rftx"). Only 102 has IDF field names. Every other block name
is NAME-ONLY, taken from the libphy init function that writes it.

## 1. Headline results

1. **Classic BBPLL reg 11 bit 0 is named `I2C_BBPLL_DIV_DAC` in IDF, and libphy clears it.**
   Classic IDF `components/soc/esp32/include/soc/regi2c_bbpll.h` lines 173-175 define
   `I2C_BBPLL_DIV_DAC` = reg 11, MSB 0, LSB 0 (also `DIV_CPU` = reg 11 bit 1, `ENDIV5` = reg 11
   bit 7, `BBADC_DIV` = reg 10 `[5:4]`). The name is NAME-ONLY: **the physical effect of this bit on a
   classic DAC clock is an S3-derived HYPOTHESIS** (S3 `rom_dac_rate_set` writes its own
   `DIV_DAC`, reg 4 bit 4; name match only). Writes, VERIFIED-BINARY/source: IDF clock init writes
   reg 11 as a whole byte, `0x43` (320 MHz) or `0xc3` (480 MHz), so `DIV_DAC = 1`. Then libphy
   `phy_i2c_init` does read-modify-write `reg11 = reg11 & 0xfe`, so `DIV_DAC = 0` (§2).
   **Idle read DONE** ([`../dac-clock-read/`](../dac-clock-read/), two identical reads): reg 10 =
   `0x10`, reg 11 = `0xc2`, so `DIV_DAC = 0`, `DIV_CPU = 1`, `ENDIV5 = 1`. That equals `0xc3 & 0xfe`,
   matching the prediction from the IDF write plus the libphy clear. There is no evidence of a later
   PLL reconfiguration at idle; the value is idle-only and was not read during playback. The earlier
   statement "no classic DAC-rate routine" (V§1.4, V§6) holds for a *named routine*. The bit is
   written on every path that reaches `phy_i2c_init`.
2. **Cross-chip reading of that bit (HYPOTHESIS):** on the S3, `dactrig` sets
   `bit15 = (rate != 1)`, and `rom_dac_rate_set(r)` sets `DIV_DAC = r`. So S3 rate 0 means
   DIV_DAC = 0 together with bit 15 = 1. On the classic chip, after PHY init, DIV_DAC = 0. That
   is consistent with, but does not prove, our measured **bit 15 = 1 (80 MS/s) engine setting**.
   The physical DAC clock role of classic reg 11 bit 0 is an S3-based HYPOTHESIS (name match only).
   If the DAC clock follows DIV_DAC, it would already run at the "rate 0" setting without any extra
   step. The idle read (§1.1) confirmed `DIV_DAC = 0`; whether it drives the DAC is untested.
3. **S3 `rom_dac_rate_set` is itself unreferenced.** No `call8` to it or to its trampoline
   `__call_rom_dac_rate_set` (`0x400061ec`) exists anywhere in the S3 ROM, and no S3 libphy or
   librftest object loads its `g_phyFuns` slot `0x1dc`. So the S3 "recipe" is also built from
   pieces no vendor code chains together, the same as `dactrig` (unreferenced, V§5). VERIFIED-BINARY
   (absence scan).
4. **The bandwidth switch looks like the same register on both chips (equivalence of code shape
   not established as identical).** Classic `ram_bb_bss_cbw40_dig` writes `DPORT_WIFI_BB_CFG_REG`
   (`0x3ff00024`): bit 3 cleared and bit 2 set to `en&1` (not a single `[3:2]` value; the
   encoding is `(en&1)<<2` over a cleared 2-bit field). S3 `rom_bb_bss_cbw40_dig` (`0x40038730`)
   writes `SYSCON_WIFI_BB_CFG_REG` (`0x6002600c`) similarly, but identical code shape was not
   established. VERIFIED-BINARY for each write separately. On
   the S3 this is **separate** from `dac_rate_set`, so cbw40 is not the DAC rate there. On the
   classic chip it is a second DAC/BB-clock candidate (HYPOTHESIS, §2).
5. **"txdump" is weaker evidence for an IQ buffer than V§5 assumed.** DWARF names the
   `get_txdumpaddr` parameters `txdump_addr, plcp_11g_len`. The value is 12. The function sits in
   `crypto_common.c` next to `get_encapaddr`, `crypto_encap` and `crypto_decap`, which are MAC
   frame and crypto tests. Read together, "txdump" plausibly means TX *frame bytes* for MAC tests,
   not DAC samples (§5). That corroborates the parent's independent finding.
6. **The only classic on-chip RF-output observable is the TX power detector (pwdet SAR).** The
   vendor reads it with `0x6000e050`/`0x6000e080` and uses it to measure *baseband-generated tones*
   at the PA (TX IQ cal, power control). In principle it can tell DAC-to-RF apart from no
   DAC-to-RF. It only means anything with the TX chain powered, so it needs keyed RF and user
   approval (§6). The TX→RX analog loopback (`rom_loopback_mode_en`, I2C 103 reg 0 bit 6) is a
   second, non-PA observable (§6).
7. **The `[27:20]` count duplicate has no classic writer.** Every `extui …,0,8; slli …,20` in the
   classic binaries was checked. The only hit is `bt_le_common.o:set_le_tx_attributes`, a BLE
   packet field in `0x6003241c/20`. VERIFIED-BINARY (absence scan).

## 2. TX-DAC clock / rate candidates

| Name (object, offset) | What it writes (quoted) | Callers | Class |
|---|---|---|---|
| `phy_i2c_init` (`phy_chip_v7_ana.o` `.phyiram.19`) | Reads BBPLL regs 10, 11, 9 (`rom_i2c_readReg(102,4,10/11/9)` at +0x5d/+0x6f/+0x82). Batch at +0x131: `(98,1,r8)=0; (107,2,r4)=7; (102,4,r10)=(R10&0xcf)\|0x10`, so `BBADC_DIV[5:4]=1`. Batch at +0x183: `(98,1,r10)=0xb0; (107,2,r5)=8; (102,4,r11)=R11&0xfe` (`movi a13,-2; and a7,a7,a13` at +0x137), so **`DIV_DAC=0`**, other reg-11 bits kept. Further batches: `(98,1,r3)=0x77`, `(107,2,r3)=0xa8`, `(99,0,r1)=0xf3`, `(98,1,r9)=7`, `(107,2,r6)=0xb8`, `(98,1,r0)=0x30`, `(107,2,r7)=0x5d`, `(98,1,r4)=0xbf`, `(107,2,r10)=0x74`, `(103,1,r9)=0x71`, `(104,3,r0)=0x63`, `(106,2,r2)=0x68`, `(102,4,r8)=0x21`; the last 4-entry batch (+0x2ed) was only partly decoded. | `phy_wakeup_init` +0xa5 and `rf_init` +0x3e, both reached from `register_chipv7_phy` (+0xc4, +0x1f1, +0x33b) | write VERIFIED-BINARY. Field name NAME-ONLY (IDF header). "Runs on every PHY init" is HYPOTHESIS: which branch a boot takes was not traced. |
| IDF `clk_ll_bbpll_set_config` (`esp_hal_clock/esp32/include/hal/clk_tree_ll.h:491,529`) | `REGI2C_WRITE(I2C_BBPLL, I2C_BBPLL_ENDIV5 /*reg 11*/, 0x43 or 0xc3)`, so DIV_DAC=1 and DIV_CPU=1 | IDF clock init, before PHY init | source-verified |
| S3 `rom_dac_rate_set` `0x40035eac` (comparison) | if `readReg_Mask(102,…,4,1,1)==0` (S3 `MODE_HF`): `0x6000608c[27]=r`, then S3 `DIV_DAC` (reg 4 bit 4) = r, then block 103 reg 2 bit 4 = r | **none** (see §1.3) | VERIFIED-BINARY |
| `ram_bb_bss_cbw40_dig` (`.phyiram.0`, slot 0x70) | `DPORT_WIFI_BB_CFG` bit 3 cleared, bit 2 = `a2&1` (`movi a8,-13; slli a2,a2,2`) | `bb_bss_cbw40` | VERIFIED-BINARY. "40 MHz BB clock" is NAME-ONLY. Effect on DAC rate is HYPOTHESIS. |
| `ram_bb_bss_bw_40_en` (slot 0x50) | same register, bit 3 cleared, bit 2 set | — | VERIFIED-BINARY |
| `bb_bss_cbw40(mode)` (`.phyiram.4`) | mode 0: `cbw40_dig(0)`, `bb_bss_cbw40_ana(0)`, `tx_delay_cfg(0)`, `0x6001c450 &= ~0xc`. mode ≠ 0: `cbw40_dig(1)`; mode 1: `ram_cbw2040_cfg(1)` + `ana(0)`, else `cbw2040_cfg(0)` + `ana(1)`; mode 3 also sets `0x6001cc0c[0]`; then `tx_delay_cfg(1)`, `0x6001c450 \|= 0xc` | Wi-Fi channel/bandwidth setup | VERIFIED-BINARY |
| `ram_cbw2040_cfg(en)` (`.phyiram.1`) | `0x60033c6c[27] = en` (MAC), `0x6001d000[6] = en` (BB) | `bb_bss_cbw40` | VERIFIED-BINARY |
| `bb_bss_cbw40_ana` (`phy_chip_v7_ana.o` `.phyiram.21`) | several I2C writes to block 103 (reg 9 and computed regs) | `bb_bss_cbw40` | VERIFIED-BINARY (writes); role NAME-ONLY (analog BW) |
| `tx_delay_cfg(cbw)` | FE2 `0x600050f0[8:0]` (V§6: 240 or 100), selected by the cbw flag | `bb_bss_cbw40`, `tx_paon_set` | VERIFIED-BINARY |
| `chip_v7_adc_wr_dly` | BBPLL reg 8 (whole) and reg 9 `[3:0]`, named `BBADC_DELAY*` | ADC timing | VERIFIED-BINARY; ADC-side, not DAC |
| `rom_clk_force_on_vit` `0x40003710` | `0x6001cc40` only (NRX) | — | Viterbi clock force. Not TX. |

`DPORT_WIFI_BB_CFG_REG` (`0x3ff00024`, IDF: "R/W [31:0]", no field names). Its other writers (list not exhaustive; other cfg writers, and any `dactrig` bit 15 interaction, were not verified):
- `phy_wifi_bb_reset` sets bit 0.
- `mac_enable_bb` sets bit 28, then toggles bit 1 0→1 three times and leaves it 1.
- `phy_close_rf` and `reset_rf_dig` clear bit 1.
- librftest `crypto_encap` writes `2` (bit 1 only, a whole-register store) right before
  `0x60033dc0 = 0x8000ffff`.

All VERIFIED-BINARY; the roles are unknown. **Bit 1 is a BB/MAC enable that `phy_close_rf`
drops.** A playback attempt after any RF-close path would need it set again (HYPOTHESIS).

## 3. Sample-RAM ownership

- `DPORT_IRAM_DRAM_AHB_SEL_REG` (`0x3ff000a8`, `MAC_DUMP_MODE[6:5]`) has exactly two classic
  vendor writers: libbttestmode `bt_bb_dump` (V§5) and librftest **`mac_init`**, which is new here.
  `mac_init` +0x2e2..+0x304 writes `0x60033dc4 = 0x03020100`, then
  `0x3ff000a8 = (old & ~0x60) | 0x40`, so **`MAC_DUMP_MODE = 2`** (lower 32 KiB bank to RF, per
  the capture-side measurement). This is a generic MAC init, not a TX routine. No TX-side writer
  exists. VERIFIED-BINARY (literal index
  over all four classic libraries and the ROM PHY range).
- The S3 counterpart is `SENSITIVE_INTERNAL_SRAM_USAGE_3_REG` `0x600c101c`
  `INTERNAL_SRAM_MAC_DUMP_USAGE[3:0]` (IDF `esp32s3/.../sensitive_reg.h:101`). S3
  **`adctrig`** writes its low nibble to 4 (`movi a6,-16; and; movi a6,4; or` at +0xb3..+0xc5).
  S3 `dactrig` does not touch it. So the "0/4 owner for playback" reading in the register map
  comes from the S3 *capture* routine, not from the playback routine. VERIFIED-BINARY.

## 4. Transmit data source selector

- No classic vendor function selects a TX data source for `0x60033d98`. That repeats V§5 and is
  re-confirmed by the full register index: `0x60033d98` appears nowhere.
- New candidate path (HYPOTHESIS): the **FE PBUS sequence memory**, which the hardware TX on/off
  sequencer plays when the MAC starts a frame:
  - `ram_set_pbus_mem` (slot 0x30, override of ROM `0x400031a4`, which copies two 20-byte
    ROM tables `0x3ff96654/68`) programs `0x60006030..0x60006044` (index/control) and FE2
    `0x60005034`/`0x60005038` (address with strobe `0x200<<8` in `[17:8]`, then data).
  - librftest `tx_pbus_set` and `pa_pbus_set` (`wifi.o`) append entries: `0x60006034` for TX,
    `0x60006038` for PA, start/end indices in `[7:0]`, `[23:16]` and `[31:24]`, constants
    `0x4401ff`, `0x5401ff`, `0xf30000`. They are called from `force_txon_en`.
  - The write mechanics are VERIFIED-BINARY. The role ("hardware PBUS sequence the MAC fires on
    TX") is NAME-ONLY.
  - Why it matters: our keying forces PBUS by hand (V§4). If the playback engine expects the
    MAC-triggered sequence, the forced state may differ from it.
- Capture-side mux for contrast: `bt_bb_dump` / `rw_rx_dump` (V§5) and `BT_rx_dump →
  adctrig(0x1fff, x, x, 0)`. Nothing on the TX side.

## 5. txdump buffer / clear

| Function | Body | Callers | Class |
|---|---|---|---|
| `get_txdumpaddr(txdump_addr*, plcp_11g_len*)` | `*a2 = 0x3ffe8000; *a3 = 12` | none (no `U` in any esp32 lib) | VERIFIED-BINARY. Parameter names from DWARF. |
| `clear_txdumpmem` | fills `0x5aa55aa5` (V§5) | none | VERIFIED-BINARY |
| `get_encapaddr` | empty (`entry; retw.n`) | — | VERIFIED-BINARY |

The DWARF unit `crypto_common.c` also holds `crypto_encap/decap/enmic`, `PSDU0_OFFSET`,
`plcp_11g_len` and `tx_a_frame`. That makes "txdump" most likely MAC frame (PSDU) staging in the
same SRAM, not DAC samples. **Consequence:** V§5's sentence "supports the window being TX sample
memory" should be read as *neutral*. The window is shared SRAM that the vendor used for something
TX-related, of unknown format. The `0x5aa55aa5` vs `0xa55aa55a` link stays coincidental.

## 6. Tone stop, PA preparation, power detector, loopback (side effects)

Pure-ROM functions (no libphy override unless noted), with what they key or write:

| Function | Effect (quoted) | Keys RF? |
|---|---|---|
| `ram_meas_tone_pwr_db` (RAM override of ROM `0x40006004`; "same shape" is unverified, ROM-vs-RAM behavior not separately traced) | `start_tx_tone_step(1, 128, g, en2, f2, 0)` → `rom_get_power_db(0x138)` → `stop_tx_tone(1)`. **Side effect: b8 keeps f = 128 and the gain field. Only bit 18 is cleared.** bc is written with en2/f2 = a15 (not resolved; ROM uses `<a13>`). | **Yes**: a tone at offset 128 frequency units |
| `rom_txtone_linear_pwr(mode)` `0x40005290` | 4 × `get_fm_sar_dout`; if mode==0, accumulates `(d1<<10)/d0`. No tone of its own. Caveat: the SAR read as traced omits `d0==0` and mode guards (possible divide-by-zero / unguarded path). | No, but meaningless without a tone and an enabled pwdet |
| `rom_get_fm_sar_dout` `0x40005204` | `0x6000e050`: clear bit 1, set bit 1; `ets_delay_us(10)`; poll `[26:24]==0` with **no timeout** (potential hang if SAR unpowered); then `read_sar_dout` | writes the SAR trigger only |
| `rom_read_sar_dout` `0x400051c0` (override `ram_read_sar_dout`) | reads 8 words `0x6000e080..e09c`, inverts and corrects each (`xor -1; extui 0,16; …`) | read only |
| `ram_en_pwdet` / `rom_en_pwdet` | V§4: power-detector SAR power-up (`0x6000e05c`, `0x6000e050`, `0x600060c0[7]`, ROM also `0x6000880c[19:18]`) | no, but it is a write |
| `rom_loopback_mode_en(en)` `0x400030f8` (slot 0x28) | I2C `(103,1,reg0,[6:6]) = en`; **`set_txclk_en(en)`**; `set_rxclk_en(en)` | Not shown. No `xpd_tx_on`/PA. It does enable the TX clock `0x600060a0[17:16]`. |
| `rfcal_txiq` (libphy) | `txcal_debuge_mode`, PBUS forces, `loopback_mode_en(x)`, `txdc_cal_v70`, `set_dco`, `start_tx_tone_step(1, f, g, …)`, `txtone_linear_pwr(0)`, `txiq_cover`, `txcal_work_mode`, `loopback_mode_en(0)`. Reads and writes `0x600050dc`. | **Yes** (cal tone) |
| `rom_txiq_set_reg(v, sel)` `0x40005154` | sel ≠ 0: `0x600050dc[4:0] = clamp(v, ±15)`; sel = 0: `0x600050dc[10:5] = clamp(v, ±31)` | no (digital TX IQ trim) |
| `rom_pbus_set_dco` `0x40004638` | `force_test(2,1,·)`, `(3,1,·)`, `(2,a10,·)`, `(3,2,·)`: the TX DC-offset rows | forces PBUS; no tone |
| `rom_txdc_cal_v70` / `ram_txdc_cal_v70` | starts rows 2/3 at `0x100` (mid-scale), iterates; libphy reads `0x6000e04c` (same SAR block) | runs with TX on inside cal |
| `rom_pbus_xpd_tx_off` `0x40004590` | `force_test(4,1,0)`, `(5,1,0)`, `(1,x,0)`, `(1,2,0)`, `(0,1,x)` | turns TX off |
| `phy_close_rf` | `DPORT_WIFI_BB_CFG[1]=0`; `pbus_debugmode`; `force_test(1,1,0)`; `pbus_workmode`; `RTC_CNTL_ANA_CONF &= 0x27ffffff` (clears `PLL_I2C_PU`, `CKGEN_I2C_PU`, `RFRX_PBUS_PU`, `TXRF_I2C_PU`; IDF names) | turns RF off |
| `tx_cont_en` / `tx_cont_dis` (`phy_chip_v7.o`) | I2C `(103,1,reg3,[6:0])` and `(…,reg4,[6:0])` = `chip7_sleep_params[84 or 86]` + {22,24} / {18,17} (en) or {−2, +0} (dis). `chan14_mic_cfg` writes 76/78 to the same fields. | no. NAME-ONLY: block 103 regs 3/4 are TX analog filter codes. They would bound the playback bandwidth (HYPOTHESIS). |

TX IQ/DC values at idle (from the map's idle read `0x600050dc = 0xd95e1f43`): `[4:0] = 3`,
`[10:5] = 0x3a` (−6). They are applied on the digital TX path that tones use. Whether the
playback samples pass through it is UNKNOWN.

### Do any of these discriminate DAC-to-RF?
- **pwdet SAR: yes in principle, but only keyed.** The vendor measures baseband tones at the PA
  through it (`rfcal_txiq`, `meas_tone_pwr_db`). A discriminating run would be: TX chain on
  (`K 0`-style), **tone off**, then compare `get_fm_sar_dout` with the engine playing a zero buffer
  and with it playing a constant full-scale buffer. A rise that follows the samples means samples
  reach the PA. It is immune to the "RX deaf while keyed" problem that blinded the
  self-observation test. Caveats: it is a square-law detector; LO leakage sets a floor; scale
  unknown. **Keys RF, so it needs user approval.** HYPOTHESIS until run.
- **Analog loopback (103/0 bit 6): discriminates DAC→baseband, not RF.** With loopback on and a
  concurrent capture, a sample-shaped pattern in the capture would show that the DAC is fed,
  without the PA. Whether loopback alone radiates is not shown. It enables the TX clock, which
  our `K 1` never did (V§4). It is an unkeyed write experiment and still needs approval. HYPOTHESIS.
- `meas_tone_pwr_db` / `txtone_linear_pwr`: these measure the *NCO tone*, not playback. Use them
  only as the positive control for the pwdet method.
- `0x600060c4` (tone 3) is already MEASURED zero in the K0/ch1 keyed phases (parent's note). This
  audit adds nothing to it.

## 7. `0x60033d98` and libpp sleep save/restore (independent check)

libpp `wdev.o`:
- `wdev_mac_reg_store` copies with `wdev_bank_store(buf+0x374, 0x3ff73c00, 120)`.
- `wdev_mac_reg_load` copies with `wdev_bank_load(0x3ff73c00, buf+0x374, 120)`.
- The next buffer offset is `0x554`, and `0x554 − 0x374 = 0x1e0 = 120 words`, so the copy covers
  `0x3ff73c00..0x3ff73ddc`, which **includes `d98`** (and `d90`, `d00..d20`).
- Callers: `wdev_mac_sleep` (store) and `wdev_mac_wakeup` (load), only.

VERIFIED-BINARY (store/load ranges and callers); it corroborates the parent. This is sleep
save/restore, not a TX recipe.
Chain, from relocations (see `tx-path-search.md`): `pm_mac_sleep` → `wdev_mac_sleep` →
`wdev_mac_reg_store`. `pm_mac_sleep` is also referenced from `libnet80211` `ieee80211_ioctl`.
**Whether any of this runs in our images is unverified** (no check of callers' runtime gating, sdkconfig
or whether our stage firmwares link `libpp`). HYPOTHESIS: if the Wi-Fi stack and modem sleep were
active, a wakeup would write back `d98` and the `d00..d20` slots. Writing `d00..d20` hangs our chip from
user code (map §8), and restoring `d98` with run set could restart the engine. The stage firmwares
are not known to start the Wi-Fi stack, but that is not shown to rule this path out.

## 8. Not found on the classic chip (absence scans, VERIFIED-BINARY)
- Any vendor function that programs playback: no `0x60033d98` writer, no `[27:20] = count&0xff` writer (§1.7). The only `d98` write is the libpp sleep-restore bulk copy (§7), not a programming routine.
- Any caller of `get_txdumpaddr` or `clear_txdumpmem`.
- Any TX-side `MAC_DUMP_MODE` writer (§3).
- Any writer of `0x6000608c` (V§6, unchanged).
- A named classic DAC-rate function. The `DIV_DAC`-named bit is written only inside `phy_i2c_init`'s batch (IDF clock init writes it as part of the whole reg 11 byte).

## 9. Safe-to-read vs may-key list for the candidates above

Pure reads (no analog or FE writes). Each still needs a bench session:
- **DONE** ([`../dac-clock-read/`](../dac-clock-read/)): BBPLL reg 10 = `0x10`, reg 11 = `0xc2`
  (`DIV_DAC = 0`) and `DPORT_WIFI_BB_CFG` `0x3ff00024` = `0x10000002` (bit 1 and bit 28 set, bits
  2/3 clear), all at idle. Not yet read during playback or keyed states.
- `0x60006030..0x60006044` PBUS-sequence index registers, idle.
- `0x600050dc`, already read at idle (above).

Unkeyed writes (expected not to radiate, not proven; user approval needed): `get_fm_sar_dout` (SAR trigger and unbounded poll; can hang if SAR is unpowered)
(pulses `0x6000e050[1]`), `en_pwdet`, `loopback_mode_en(1)` (also enables the TX clock), setting
or clearing BBPLL `DIV_DAC`, and writing `DPORT_WIFI_BB_CFG` bits 2/3. Writing BBPLL reg 11 also holds
`DIV_CPU`. A wrong value there can retune the CPU clock. Do not write it without a plan.

Key or force RF (approval required): `meas_tone_pwr_db`, `rfcal_txiq`, `txiq_cal_init`,
`txdc_cal_*`, `txcal_debuge_mode`, `tx_cont_en` followed by any TX, `force_txon_en`,
`tx_pbus_set`/`pa_pbus_set`, `set_pbus_mem` (reprograms the hardware TX sequence), and the pwdet
playback discriminator in §6.
