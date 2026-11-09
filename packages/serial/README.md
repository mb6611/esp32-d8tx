# @d8tx/serial

Implementations of the `SerialPort` interface from `@d8tx/core`.

- `src/web.ts`: Web Serial (Chrome, Edge, Electron), USB ids for DevKits (CP2102, CH340, CH9102) and for flight controllers, picking an already-granted port.
- `src/node.ts`: Node (macOS/Linux) transport for the bench scripts and hardware tests; dev only, never used by the UI. Plain fd reads, not the `serialport` package.
- `src/mock.ts`: a simulated DevKit and drone (`MockPort`, `MockDronePort`) that replay real captures; this is what `?mock=1` uses.

## Build and test

```sh
pnpm --filter @d8tx/serial typecheck
pnpm --filter @d8tx/serial test
```

`src/node.hw.test.ts` talks to real hardware and is meant for the bench (see [how-to/hw-check-and-e2e.md](../../docs/how-to/hw-check-and-e2e.md)); `link.test.ts` and `web.test.ts` run offline.
