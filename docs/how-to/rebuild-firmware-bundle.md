# Rebuild the firmware bundle

The web and desktop apps flash the images in `apps/web/public/firmware/`. After changing anything in `firmware/main/`:

```sh
make -C firmware test      # offline host tests, no ESP-IDF needed
make -C firmware web       # idf.py build, then copy bootloader, partition table, app and manifest.json
make -C firmware version   # the version string of the current sources
```

`make web` needs ESP-IDF (the Makefile sources `$IDF_EXPORT`, default `~/esp/esp-idf/export.sh`). `firmware/tools/web_bundle.mjs` reads offsets from the build's `flasher_args.json`, refuses to bundle if the build's version differs from the sources' version (`fw_version.mjs`), and writes sizes and sha256 of each image into `manifest.json`.

`apps/web` checks the bundle against the sources at `dev` and `build` time (`scripts/check-firmware.mjs`), so a stale bundle fails the build. The version INFO reports is `<semver>+<hash8>`, with the hash computed from the sources (`tools/fw_version.mjs`), so any source change gives installed DevKits an update offer.
