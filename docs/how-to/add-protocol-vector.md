# Add a protocol vector

Golden vectors in `protocol/vectors/*.json` are the single source of truth shared by the Python, TypeScript and C implementations. They are generated, not hand-written.

1. Add the case to `python/tools/gen_vectors.py` (it builds vectors with the Python reference in `python/d8tx`).
2. Regenerate: `python3 python/tools/gen_vectors.py`, and review the diff in `protocol/vectors/`.
3. Make each consumer check it:
   - TS: `packages/core/src/*.test.ts`, loading with `vec('<name>')` from `packages/core/src/vectors.ts`; run `pnpm --filter @d8tx/core test`.
   - Python: `python/tests/test_vectors.py`; run `python/.venv/bin/pytest python/tests`.
   - Firmware C: `firmware/test/test_vectors.c`, run by `make -C firmware test`.

`protocol/vectors/commands.h` is the generated command table the firmware tests compile against. Protocol reference: [protocol/PROTOCOL.md](../../protocol/PROTOCOL.md).
