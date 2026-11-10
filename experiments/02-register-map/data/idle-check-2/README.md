# B1a idle read, part 2 (classic ESP32, 2026-11)

Method: same as `../idle-check/` (txeng already flashed, RTS reset, only `R <addr>` lines, two passes; no K/T/M/Y/W/Q,
no rx_mode, no engine run, no keying, no writes, no flash backup/restore). Offline check first: txeng `R` refuses only
`0x60033d00..0x60033d23` and unaligned addresses (`txeng.c` `forbidden()`); all five are aligned and outside that range,
and the handler is a plain `REG_READ`. Script `idle_read.py`, raw log `logs/idle_read.log`. Boot: `ahb_sel=00000000 txe=00000000 tone0=2003a020`.
Both passes identical.

| Register | Value | Decode (exact bits) |
|---|---|---|
| `0x600060c0` | `0x00000081` | bits 7 and 0 set; rest 0. Bit18 (enable) clear. Unmapped otherwise (not a negated keyed gain: `[17:10]`=0). |
| `0x6000880c` | `0x002c000a` | bits 21, 19, 18, 3, 1 set. Bits `[19:18]`=0b11 (SAR power field, not TX; leave alone). Others unmapped. |
| `0x3ff000a8` | `0x00000000` | `[6:5]` MAC_DUMP_MODE = 0 (no bank owner), no capture-side ownership at idle. |
| `0x60033d90` DUMP_CTRL | `0x00000000` | count 0, bit31 enable clear, bit18 done clear, no trigger; idle. |
| `0x60033d98` engine | `0x00000000` | bit31 run clear, bit18 done clear, count 0; engine idle. |
