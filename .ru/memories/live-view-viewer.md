---
name: live-view-viewer
description: Read before working on live view / waterfall display for the DevKit V1 SDR (bridge, gqrx, SDR++), or before planning screenshots as evidence.
load: description
---
The user switched the live-view target from gqrx to SDR++ on 2026-11-05; `esp32sdr bridge`
must stay the one bridge implementation and any launcher (`esp32sdr sdrpp`) only wraps it.

**Why:** the user asked for SDR++ instead of gqrx and said the launcher must not duplicate
bridge logic ("bridge alone + SDR++ by hand must behave identically").
Agents on this machine had no macOS Screen Recording permission then (`screencapture`
fails); the user said to skip screenshots and rely on logs/byte counts, they look at the
screen themselves.
**How to apply:** check docs/devkitv1/live-view.md for the current command; don't plan on
screenshots unless the user says permission was granted.
