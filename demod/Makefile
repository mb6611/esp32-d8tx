# d8demod build. Use from anywhere: make -C demod <target>
# Targets: all (=wasm), wasm, test (native), check (wasm + node cross-check), esp32 (compile-only), clean
HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
SRC  := $(HERE)src/d8demod.c
INC  := $(HERE)include
RT   := $(HERE)wasm/rt.c
DIST := $(HERE)dist
CAPS := $(HERE)../protocol/captures

CFLAGS := -O2 -Wall -Wextra -Werror -I$(INC)
WASM_LDFLAGS := -Wl,--no-entry -Wl,--export-dynamic -Wl,--allow-undefined -Wl,-z,stack-size=65536 \
  -Wl,--export=d8_decode -Wl,--export=d8_work_size -Wl,--export=d8_opts_default
LLD_DIR := $(dir $(shell command -v wasm-ld 2>/dev/null || echo /opt/homebrew/bin/wasm-ld))
XTENSA_GCC ?= $(lastword $(sort $(wildcard $(HOME)/.espressif/tools/xtensa-esp-elf/*/xtensa-esp-elf/bin/xtensa-esp32-elf-gcc)))

.PHONY: all wasm test check esp32 clean
all: wasm
wasm: $(DIST)/d8demod.wasm

# Fails unless the module imports exactly atan2f, sinf, cosf, floorf from env.
$(DIST)/d8demod.wasm: $(SRC) $(INC)/d8demod.h $(RT)
	@mkdir -p $(DIST)
	PATH="$(LLD_DIR):$$PATH" clang --target=wasm32 $(CFLAGS) -nostdlib -ffreestanding -fno-builtin-sincosf \
	  $(WASM_LDFLAGS) $(SRC) $(RT) -o $@
	node $(HERE)wasm/check_imports.mjs $@

$(DIST)/test_decode: $(HERE)test/test_decode.c $(SRC) $(INC)/d8demod.h
	@mkdir -p $(DIST)
	$(CC) -std=c99 $(CFLAGS) $(HERE)test/test_decode.c $(SRC) -lm -o $@

test: $(DIST)/test_decode
	$(DIST)/test_decode $(CAPS) $(HERE)test/expected.txt

check: wasm
	node $(HERE)wasm/check.mjs

# Compile-only with the ESP-IDF xtensa toolchain (not linked into firmware).
esp32:
	@test -x "$(XTENSA_GCC)" || { echo "xtensa-esp32-elf-gcc not found (set XTENSA_GCC)"; exit 1; }
	@mkdir -p $(DIST)
	$(XTENSA_GCC) -std=c99 -Os -Wall -Wextra -Werror -I$(INC) -c $(SRC) -o $(DIST)/d8demod.xtensa.o
	@echo "xtensa compile ok ($(XTENSA_GCC))"

clean:
	rm -f $(DIST)/d8demod.wasm $(DIST)/test_decode $(DIST)/*.xtensa.o
