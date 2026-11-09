# apps/web

The browser build: Vite wrapping `@d8tx/ui`, plus the worker (`src/worker.ts`) that runs `@d8tx/core` and the WASM demodulator. No backend: everything runs in the page and a Web Worker, with Web Serial for both ports. Needs Chrome or Edge.

## Build and run

```sh
pnpm install
pnpm --filter web dev        # builds demod wasm, checks the firmware bundle, starts Vite
pnpm --filter web build      # + typecheck and vite build into dist/
```

`demod` needs `clang` with the wasm32 target and `wasm-ld`. Open `?mock=1` for the simulated DevKit and drone. There are no tests in this package; the logic is tested in `core`, `serial` and `ui`.

## Key files

- `src/main.tsx`: mounts the app and starts the worker.
- `src/worker.ts`: wires the `Host` to Web Serial and mock ports; loads `d8demod.wasm`.
- `public/firmware/`: the firmware bundle the in-app flasher writes (`make -C firmware web`); `scripts/check-firmware.mjs` fails the build if it is stale.
- `vite.config.ts`.
