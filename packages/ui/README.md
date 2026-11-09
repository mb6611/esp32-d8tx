# @d8tx/ui

The React app, shared by the web and desktop builds: `App` and `ErrorBoundary` exported from `src/index.ts`. It talks to the worker (`@d8tx/core` `Host`) by messages only; it never opens a serial port itself except for the firmware flasher.

## Build and test

```sh
pnpm --filter @d8tx/ui typecheck
pnpm --filter @d8tx/ui lint
pnpm --filter @d8tx/ui test      # vitest
```

## Key files

- `src/App.tsx`, `src/useController.ts`: layout, keyboard and stick input, arm gate (hold R to arm, X disarms), `?mock=1` mode.
- `src/PairingPanel.tsx`: port selection, Connect, Bind.
- `src/DronePanel.tsx`, `src/Quad3D.tsx`: drone telemetry and the 3D model.
- `src/SettingsDialog.tsx`, `src/persist.ts`: settings and their storage.
- `src/flash/`: in-app firmware install/update (`flasher.ts` speaks the ESP32 ROM bootloader, writes bootloader + partition table + app only, verifies by MD5).
- `src/linkState.ts`: link/bind state shown in the UI.
