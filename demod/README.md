# demod

Small C demodulator for FrSky D8 telemetry replies from 8-bit I/Q: `src/d8demod.c`, API in `include/d8demod.h`. It is built twice: to WebAssembly for the apps (and the Python/Node hosts), and natively for tests. No libc: the WASM imports only `atan2f`, `sinf`, `cosf`, `floorf`.

## Build and test

```sh
make -C demod wasm     # dist/d8demod.wasm (needs clang with wasm32 target and wasm-ld)
make -C demod test     # native decode test against test/expected.txt
make -C demod check    # wasm + Node cross-check against protocol/captures
make -C demod esp32    # compile-only check for the Xtensa toolchain
```

## Key files

- `src/d8demod.c`: the decoder.
- `wasm/rt.c`: tiny runtime for the freestanding build; `wasm/check_imports.mjs` fails the build if the import list changes.
- `test/test_decode.c`, `test/gen_expected.py`: native test and its expected output.

Consumers: `packages/core/src/worker/demod.ts` (WASM loader), `python/d8tx/demod.py`.
