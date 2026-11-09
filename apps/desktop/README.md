# apps/desktop

An Electron shell around the web build (`apps/web/dist`), served as `app://d8tx/`. It runs the same app with `backgroundThrottling: false` (so a minimized window keeps the 111 Hz link going) and picks the DevKit and FC ports by USB id.

## Run and package

```sh
pnpm --filter desktop dev        # builds the web app, runs electron .
pnpm --filter desktop package    # macOS dir build with electron-builder (release/)
```

Set `D8TX_ESP_PORT` / `D8TX_FC_PORT` to pick ports for tests. There are no unit tests; the hardware end-to-end is in `e2e/` ([how-to/hw-check-and-e2e.md](../../docs/how-to/hw-check-and-e2e.md)), validation record in [docs/validation/d8tx-web-desktop.md](../../docs/validation/d8tx-web-desktop.md).

## Key files

- `main.cjs`: window, `app://` protocol, serial port selection by USB id.
- `preload.cjs`: tells the main process which role's USB filter a port request uses.
- `probe.html`, `probe-worker.js`: port probing to tell the DevKit from the FC.
- `e2e/run.mjs`, `e2e/tap.mjs`: Playwright `_electron` harness and the observer it injects; raw results in `e2e/results/`.
