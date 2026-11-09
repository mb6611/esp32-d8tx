# esp32-d8tx

Private research repository: transmitting FrSky D8 from a classic ESP32 DevKit V1 and
flying a D8 receiver (Betaflight on a CC2500 board) from a browser.

- `firmware/` — ESP-IDF project `d8tone`: the ESP32 TX firmware the host talks to over UART
  (protocol: [protocol/PROTOCOL.md](protocol/PROTOCOL.md)).
- `packages/core`, `packages/serial`, `packages/ui`, `apps/web`, `apps/desktop` — pnpm workspace: the TypeScript
  link/telemetry/FC core, Web Serial transport, shared React UI, the web app and the Electron desktop app.
- `demod/` — C demodulator for D8 telemetry (native, WASM, ESP32 builds; `Makefile`).
- `protocol/` — `PROTOCOL.md`, golden vectors and I/Q captures shared by Python, TS, firmware and demod tests.
- `python/` — `d8tx` reference library (`D8Link`, `BetaflightMSP`) and vector generator; the FastAPI server was retired.
  See [python/README.md](python/README.md).
- `bench/d8-tx/` — bench runner, D8 decoder (`host/d8.py`, `host/hopfollow.py`), tests, analysis,
  raw results (the evidence behind the write-up). [bench/d8-tx/README.md](bench/d8-tx/README.md).
- `bench/cc2500-rxdiag/`, `bench/betaflight-patch/`, `bench/blackbox/`, `bench/register-map/` —
  receiver-side diagnostics, Betaflight patches and radio register notes.
- `docs/devkitv1/writeup/` — the write-up: [TX chapter](docs/devkitv1/writeup/tx.md) ([HTML](docs/devkitv1/writeup/index.html)).
  The RX chapters are kept for the story; their code is in the public RX repo
  [mb6611/esp32-devkitv1-sdr](https://github.com/mb6611/esp32-devkitv1-sdr).

## Run
```sh
pnpm install
pnpm --filter web dev          # browser app (Web Serial)
pnpm --filter desktop dev      # Electron app
pnpm --filter desktop package  # build the desktop app
```
Hardware check: `node packages/core/scripts/hw-check.ts`; Electron e2e: `node apps/desktop/e2e/run.mjs`.
Validation results: [docs/validation/d8tx-web-desktop.md](docs/validation/d8tx-web-desktop.md).

## Offline checks (no hardware)
```sh
pnpm -r test
make -C demod test check
sh firmware/test/run.sh
python3 -m unittest discover -s bench/d8-tx/tests
bash firmware/test/run.sh
make -C bench/cc2500-rxdiag/tests test
python/.venv/bin/pytest python/tests
```

## License
Private, all rights reserved, except `bench/betaflight-patch/` and `bench/cc2500-rxdiag/`
(Betaflight derivatives, GPL-3.0-or-later). See [NOTICE.md](NOTICE.md).
