# esp32-d8tx

Private research repository: transmitting FrSky D8 from a classic ESP32 DevKit V1 and
flying a D8 receiver (Betaflight on a CC2500 board) from a browser.

- `d8tx/` — the product: `d8tone` firmware protocol ([PROTOCOL.md](d8tx/PROTOCOL.md)), Python
  `D8Link` + FastAPI server (`d8tx/python`), React "Sticks" controller (`d8tx/app`). Start here:
  [d8tx/README.md](d8tx/README.md).
- `bench/d8-tx/` — ESP32 TX firmware (`firmware/`, app `d8tone`), host bench runner, D8 decoder
  (`host/d8.py`, `host/hopfollow.py`), analysis, raw results. [bench/d8-tx/README.md](bench/d8-tx/README.md).
- `bench/cc2500-rxdiag/`, `bench/betaflight-patch/`, `bench/blackbox/`, `bench/register-map/` —
  receiver-side diagnostics, Betaflight patches and radio register notes.
- `docs/devkitv1/writeup/` — the write-up: [TX chapter](docs/devkitv1/writeup/tx.md) ([HTML](docs/devkitv1/writeup/index.html)).
  The RX chapters are kept for the story; their code is in the public RX repo
  [mb6611/esp32-devkitv1-sdr](https://github.com/mb6611/esp32-devkitv1-sdr).

## Offline checks (no hardware)
```sh
python3 -m unittest discover -s bench/d8-tx/tests
bash bench/d8-tx/firmware/test/run.sh
make -C bench/cc2500-rxdiag/tests test
(cd d8tx/python && .venv/bin/pytest)
```

## License
Private, all rights reserved, except `bench/betaflight-patch/` and `bench/cc2500-rxdiag/`
(Betaflight derivatives, GPL-3.0-or-later). See [NOTICE.md](NOTICE.md).
