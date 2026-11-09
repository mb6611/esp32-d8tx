# d8tx DevKit firmware. Needs ESP-IDF (see .ru memory esp32-bench-setup / README): IDF_EXPORT is sourced per recipe.
#   make -C firmware build   idf.py build into build/
#   make -C firmware web     build, then copy bootloader, partition table, app + manifest.json to apps/web/public/firmware
#   make -C firmware test    offline host tests
#   make -C firmware version print the version of the current sources (no ESP-IDF needed)
IDF_EXPORT ?= $(HOME)/esp/esp-idf/export.sh
IDF = . $(IDF_EXPORT) >/dev/null 2>&1 && idf.py

.PHONY: build web test version
build:
	$(IDF) build
web: build
	node tools/web_bundle.mjs build ../apps/web/public/firmware
test:
	sh test/run.sh
version:
	@node tools/fw_version.mjs
