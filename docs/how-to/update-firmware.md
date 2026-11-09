# Update the DevKit firmware

The app ships a firmware bundle (`apps/web/public/firmware/`: bootloader, partition table, app, `manifest.json`). When the DevKit runs an older version, Pairing shows **Update firmware**.

1. Connect the DevKit (Pairing → Connect). Disarm first; the button is disabled while armed or binding.
2. Press **Update firmware** → **Flash**. The link stops for about 20 s, each image is verified by MD5, then the DevKit reboots into the new firmware and the link restarts.

NVS is not touched, so the DevKit keeps its `txid` and hop table and the drone stays bound.

Without the app, use `idf.py flash` from `firmware/` (ESP-IDF 5.x). That also leaves NVS alone unless you erase flash.

To build a new bundle, see [rebuild-firmware-bundle.md](rebuild-firmware-bundle.md).
