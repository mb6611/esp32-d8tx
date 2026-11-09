# README + docs plan (owner-approved 2026-11-09)
Decisions: hero = recorded app GIF (mock mode, scripted sticks, 3D drone, telemetry; 8-10 s, ~1200 px, <5 MB) with the takeoff video (docs/devkitv1/writeup/media/esp32-first-takeoff.mp4, inline) below it; short [!CAUTION] in README, full text in REGULATORY.md (substance unchanged from docs/devkitv1/writeup/tx.md#regulatory-status and memory d8-tx-private); explanatory diagrams via Excalidraw CLI (npx @excalidraw/cli render/mermaid, local, no account) sources in docs/diagrams/ (.excalidraw/.mmd) rendered to committed SVGs by `pnpm diagrams`; measured plots stay as they are; writeup frozen as the story + a short "Since then" section; writeup copied into the app at /writeup at build (docs/ is the only source); README links /writeup once deployed, GitHub Pages once public, until then local. Every number must be checked against results files.

README mockup (<=120 lines):
1. Title; bold pitch "Fly a real FrSky D8 drone from your browser. A $5 ESP32 DevKit is the radio."; links: Live app · How it works (writeup) · Demo (no hardware) (placeholders until deployed).
2. Hero GIF (app) then takeoff video.
3. [!CAUTION] regulatory block (estimated ~-25 dBm EIRP from RSSI, not measured; harmonics not measured; link REGULATORY.md; nothing for sale).
4. What it does: 111 Hz control, ~98% packets, telemetry over radio decoded in WASM, one-click bind + firmware install over USB, no backend (Web Worker + Web Serial).
5. How it works: docs/diagrams/overview.svg; hop-e8-map | hop-esp-runB-map side by side; docs/diagrams/slot.svg; link to writeup.
6. Try it: no-hardware demo (?mock=1); hardware steps: Pairing → Connect → Install firmware → plug drone USB → Bind → unplug, battery, props, fly (hold R arm, X disarm). Pairing screenshot.
7. Status: works / not yet (range, measured power, D16, S3/C3, Firefox/Safari).
8. Repo table; links CONTRIBUTING.md, ARCHITECTURE.md; License.
Research: .ru/research/readme-viral-repos.md, .ru/research/research-repos-docs.md.
