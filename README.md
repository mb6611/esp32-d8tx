# esp32-d8tx

Private research repository: transmitting FrSky D8 from a classic ESP32 DevKit V1 and
flying a D8 receiver (Betaflight on a CC2500 board) from a browser.

- `firmware/` — ESP-IDF project `d8tone`: the ESP32 TX firmware the host talks to over UART
  (protocol: [docs/PROTOCOL.md](docs/PROTOCOL.md)).
- `python/` — `d8tx` package: `D8Link` (slot-rate sender, arm gate), `BetaflightMSP`, FastAPI
  server. Start here: [python/README.md](python/README.md).
- `app/` — React/Vite "Sticks" controller UI.
- `bench/d8-tx/` — bench runner, D8 decoder (`host/d8.py`, `host/hopfollow.py`), tests, analysis,
  raw results (the evidence behind the write-up). [bench/d8-tx/README.md](bench/d8-tx/README.md).
- `bench/cc2500-rxdiag/`, `bench/betaflight-patch/`, `bench/blackbox/`, `bench/register-map/` —
  receiver-side diagnostics, Betaflight patches and radio register notes.
- `docs/devkitv1/writeup/` — the write-up: [TX chapter](docs/devkitv1/writeup/tx.md) ([HTML](docs/devkitv1/writeup/index.html)).
  The RX chapters are kept for the story; their code is in the public RX repo
  [mb6611/esp32-devkitv1-sdr](https://github.com/mb6611/esp32-devkitv1-sdr).

## Offline checks (no hardware)
```sh
python3 -m unittest discover -s bench/d8-tx/tests
bash firmware/test/run.sh
make -C bench/cc2500-rxdiag/tests test
(cd python && .venv/bin/pytest)
```

## License
Private, all rights reserved, except `bench/betaflight-patch/` and `bench/cc2500-rxdiag/`
(Betaflight derivatives, GPL-3.0-or-later). See [NOTICE.md](NOTICE.md).
