# Local MATEKF411RXDIAG build (receive-only CC2500 diagnostic)

Editable inputs: `overlay/`, `patches/`, `SOURCES.lock`. Generated (git-ignored): `work/` (Betaflight clone, toolchains).
Build (no flash): `bash fetch.sh [--bf-mirror DIR] [--toolchain-tarball T] [--linux-toolchain-tarball T]; bash apply.sh [--force on a fresh clone]; bash build.sh` (docker, ubuntu:24.04).
Checks: `make -C ../tests test`; `python3 ../tests/check_source.py .`; `bash ../tests/check_build.sh out/<BUILD_ID>`.
BUILD_ID = sha256 prefix over overlay+patches+SOURCES.lock. The .bin is not byte reproducible: flash only the checksummed artifact in `out/<BUILD_ID>/SHA256SUMS`.

Current: BUILD_ID 3b26d459, `betaflight_4.2.11_MATEKF411RXDIAG_.bin` sha256 b5963473ef6a04d5bb1305ce6383fcb7107d610ee27a3ea8757e01cba9daa93e (390264 B).

## `rxdiag freq <freq_khz> [window_ms=100] [bw=812] [agcctrl2=251] [agcctrl1=64] [duration_ms=5000, max 60000]`
`H,proto=3,mode=freq,...,freq_word,freq_rb,fscal3..0,cal_us,hz_per_lsb=1587,txen=0,...`
`F,seq,t_us,n,rej,ncs,fe_last,fe_min,fe_max,fe_mean_raw,fe_mean_hz,rssi_max_raw,pktstatus_last,lqi,marc,flags` then `X,seq,t_us,done`.
FREQEST (signed, 26 MHz/2^14) counts only samples with PKTSTATUS CS (0x40); ncs=0 -> estimates 0 and flags bit4 (16).
