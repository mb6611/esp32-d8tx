# dac-clock-read (idle, read-only)
Added txeng command `I`: `ram_chip_i2c_readReg(102,4,10)` and `(102,4,11)` inside the existing
`portENTER_CRITICAL(&mux)`, plus `REG_READ(0x3ff00024)`. Signature/host match existing `Q` usage (0x62,1,0)
and vendor `rom_i2c_readReg(102,4,r)` in phy_i2c_init. No I2C writes, no RF key, no retune, no engine run,
no drone access. Read-only claim is for the IDLE state only.

Two idle readings after reset (log.txt), identical:
- BBPLL reg10 = 0x10, reg11 = 0xc2 -> DIV_DAC (reg11 bit0) = 0
- DPORT_WIFI_BB_CFG 0x3ff00024 = 0x10000002 (bit1 set, bit2/3 clear, bit28 set)
No timeouts or hangs. Firmware with `I` left flashed; port free.

Log note: `log.txt` stores only the parsed `V,...` response lines (plus OK/boot markers) from each
reading. It does not capture the transmitted command text; that `I` was sent is per
`dac_clock_read.py` (`s.write(b'I\n')`), not recorded in the log. No raw serial capture exists.
