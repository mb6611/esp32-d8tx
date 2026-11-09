# @d8tx/core

The host side of the link, in TypeScript with no DOM or Node dependency: D8 protocol and DevKit serial protocol (`protocol.ts`, `reader.ts`), the link controller (`link.ts`), telemetry and hub decoding (`telemetry.ts`, `hub.ts`), a Betaflight MSP client (`msp.ts`, `fc.ts`), and the worker `Host` (`worker/host.ts`) that owns both ports, bind, the arming gate and the WASM demodulator (`worker/demod.ts`). Serial ports are an interface (`port.ts`); `@d8tx/serial` supplies implementations.

## Build and test

```sh
pnpm --filter @d8tx/core typecheck
pnpm --filter @d8tx/core test     # vitest; checks against protocol/vectors and protocol/captures
```

Tests that decode real captures need `make -C demod wasm`.

## Key files

- `src/link.ts`: `D8Link`, the 111 Hz stick sender, STAT polling, bind.
- `src/worker/host.ts`: the worker-side controller the UI talks to by messages (`worker/types.ts`).
- `src/vectors.ts`: loads golden vectors; see [how-to/add-protocol-vector.md](../../docs/how-to/add-protocol-vector.md).
- `scripts/hw-check.ts`, `scripts/bind-check.ts`: bench scripts, see [how-to/hw-check-and-e2e.md](../../docs/how-to/hw-check-and-e2e.md).
