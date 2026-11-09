# Run the hardware check and the Electron end-to-end

Both need a real DevKit (and a drone FC for most runs). Props off, battery out, arming stays disallowed except in the explicit `arm` phase. One process per serial port.

## hw-check (TS core against the real firmware)

```sh
node packages/core/scripts/hw-check.ts --esp /dev/cu.usbserial-0001 --fc /dev/cu.usbmodem0x80000001 --seconds 60 --power 127 --fofs 0
```

Options: `--bind S` (bind for S seconds first), `--no-link`, `--no-esp`, `--no-fc`. With the FC on, MSP_RC is read back and compared with the sticks sent. Needs `make -C demod wasm` first. Example results: [bench/d8-tx/results/bind/SUMMARY.md](../../bench/d8-tx/results/bind/SUMMARY.md). The one-click bind path has its own script, `packages/core/scripts/bind-check.ts` (see [bind.md](bind.md)).

## Electron end-to-end

```sh
pnpm --filter web build
cd apps/desktop
node e2e/run.mjs soak 10                  # 10 min link, window minimized, per-minute stats
node e2e/run.mjs autolink                 # auto-link timings, port loss, reload, second instance
E2E_ALLOW_ARM=1 node e2e/run.mjs arm      # arm, throttle 1150 for 3 s, disarm, port loss
```

Set `D8TX_ESP_PORT` and `D8TX_FC_PORT` for your ports. Each run uses a throwaway profile under `$TMPDIR/d8tx-e2e`. Results are written to `apps/desktop/e2e/results/<phase>-<time>.json`; the validation write-up is [docs/validation/d8tx-web-desktop.md](../validation/d8tx-web-desktop.md).
