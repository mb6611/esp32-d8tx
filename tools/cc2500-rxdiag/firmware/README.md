# Local MATEKF411RXDIAG build (receive-only CC2500 diagnostic)

Editable inputs: `overlay/`, `patches/`, `SOURCES.lock`. Generated (git-ignored): `work/` (Betaflight clone, toolchains).
Build (no flash): `bash fetch.sh [--bf-mirror DIR] [--toolchain-tarball T] [--linux-toolchain-tarball T]; bash apply.sh [--force on a fresh clone]; bash build.sh` (docker, ubuntu:24.04).
Checks: `make -C ../tests test`; `python3 ../tests/check_source.py .`; `bash ../tests/check_build.sh out/<BUILD_ID>`.
BUILD_ID = sha256 prefix over overlay+patches+SOURCES.lock. The .bin is not byte reproducible: flash only the checksummed artifact in `out/<BUILD_ID>/SHA256SUMS`.

Current: BUILD_ID 4bdc8581, `betaflight_4.2.11_MATEKF411RXDIAG_.bin` sha256 06e88ff2aa8bb68e34f3e8d61834b674d2b7670b10017a3684fdaa6eeb8b3961 (395208 B). Adds `rxdiag pkt` (U6); flashed for the one-packet TX check in [../../d8-tx/results/packet/NOTE.md](../../../experiments/05-first-packet/data/NOTE.md) (receive-only diagnostic; no TX path, Betaflight not restored). Previous (freq only): 3b26d459, sha256 b5963473ef6a04d5bb1305ce6383fcb7107d610ee27a3ea8757e01cba9daa93e.

## `rxdiag freq <freq_khz> [window_ms=100] [bw=812] [agcctrl2=251] [agcctrl1=64] [duration_ms=5000, max 60000]`
`H,proto=3,mode=freq,...,freq_word,freq_rb,fscal3..0,cal_us,hz_per_lsb=1587,txen=0,...`
`F,seq,t_us,n,rej,ncs,fe_last,fe_min,fe_max,fe_mean_raw,fe_mean_hz,rssi_max_raw,pktstatus_last,lqi,marc,flags` then `X,seq,t_us,done`.
FREQEST (signed, 26 MHz/2^14) counts only samples with PKTSTATUS CS (0x40); ncs=0 -> estimates 0 and flags bit4 (16).

## `rxdiag pkt <freq_khz> [duration_ms=5000, max 60000]` (proto 4, receive-only D8 packet capture)
Single fixed channel (CHANNR=0, no hopping), LNA on after liveness, TX_EN low, ant high; STX/SFTX unreachable (guarded SPI). Allowed extras: RXBYTES status read, RX FIFO burst read (header 0xFF, 1..64 bytes), SFRX (pkt mode only), SRX/SIDLE.
Register set: stock Betaflight D8 (`work/betaflight/src/main/rx/cc2500_frsky_shared.c`: `cc2500FrskyBaseConfig` lines 73-100, `cc2500FrskyDConfig` lines 102-113, FOCCFG 0x16 from `initialiseData` line 185): MDMCFG4/3/2=AA/39/11, DEVIATN 42, PKTLEN 19, PKTCTRL0 05, FSCTRL1 08, MCSM1 0C, MCSM0 18, FIFOTHR 07, AGC 03/40/91, SYNC D391 (chip default, written explicitly). Deliberate differences: FREQ2/1/0 from the argument; IOCFG0 0x2E (poll RXBYTES, GDO0 never driven; stock 0x01); PKTCTRL1 0x04 (no CRC autoflush/addr check so CRC-bad packets show; stock data state 0x0D); PATABLE 0x00 (stock 0xFF); FSCTRL0 0.
Output: `H,proto=4,mode=pkt,...` then per packet `P,seq,t_us,len,<hex>,rssi,lqi,crc_ok` (len = hex bytes = length byte + payload; rssi raw signed byte; lqi 7 bit; crc_ok = hardware CRC_OK; t_us = first FIFO byte seen), `E,t,code,detail`, `X,seq,t,done|host|usb|usbstall|radio`.
Packet end = RXBYTES (read until two reads agree) unchanged for 500 us. Back-to-back FIFO content is split by length byte. Errors: `EPART` (short FIFO; followed by a P with the bytes seen and rssi=lqi=crc_ok=0), `EOVF` (RXBYTES bit7 / MARC 0x11 -> SIDLE, SFRX, SRX, resume; 8 in a row -> radio exit), ECFG/ENOCHIP/ECAL/EFIFO/EMOTOR. Exit always SIDLE, SFRX (FIFO flushed), LNA off.
