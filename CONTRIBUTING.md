# Contributing

Read [REGULATORY.md](REGULATORY.md) first: this repo contains transmit code, and changes must keep to it. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the layout and invariants.

## Setup

Needs Node with pnpm, clang with `wasm-ld` (for the WASM demodulator), Python 3, and ESP-IDF only if you change firmware (`~/esp/esp-idf/export.sh`, or set `IDF_EXPORT`).

```sh
pnpm install
pnpm --filter web dev          # browser app; add ?mock=1 for no hardware
pnpm --filter desktop dev      # Electron app
```

## Checks (no hardware needed)

```sh
pnpm -r typecheck
pnpm -r lint
pnpm -r test
make -C demod test check
sh firmware/test/run.sh
python3 -m unittest discover -s tools/d8-tx-host/tests
make -C tools/cc2500-rxdiag/tests test
(cd python && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/pytest)
```

Hardware checks: `node packages/core/scripts/hw-check.ts`, `node apps/desktop/e2e/run.mjs`.

## Changing things

- **Firmware:** the web app ships prebuilt images from `apps/web/public/firmware/`, kept in git. After any change under `firmware/`, run `make -C firmware web` and commit the updated images; the web build fails if they are stale or missing.
- **Protocol:** edit `protocol/PROTOCOL.md` first, then regenerate vectors with `python/tools/gen_vectors.py` and update every implementation.
- **Diagrams:** sources are in `docs/diagrams/`; run `pnpm diagrams` to re-render the committed SVGs.
- **Lab log:** `docs/lab-log/` is the original writeup, archived; do not edit it. New measurements go in a new numbered experiment under `experiments/` (see [experiments/README.md](experiments/README.md)).
- **Docs numbers:** every number must trace to a file under `experiments/*/data/` or the lab log; leave it out otherwise.
