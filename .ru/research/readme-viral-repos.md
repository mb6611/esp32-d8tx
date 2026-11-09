# What viral hardware / RF / dev-tool READMEs look like (research, 2026-11)

Question: how do READMEs of popular projects that spread on HN/X get read in seconds, and
what should the esp32-d8tx README (ESP32 → FrSky D8 → drone, flown from a browser/desktop
app, with a long technical writeup) look like?

Method: fetched the raw README of ~20 repos and read the first screen + section order.
"First screen" = roughly what fits before scrolling on GitHub desktop (~40 lines of rendered
markdown). Lengths are of the whole README.

## Part 1 — examples

### A. Hardware hacking / RF / SDR / maker

| Project | First screen | Length | Visuals | Quick start | Legal/RF | Deeper docs |
|---|---|---|---|---|---|---|
| **LoLRa** (cnlohr) — ESP32/CH32 transmit LoRa with no radio. Closest analog to d8tx. https://github.com/cnlohr/lolra | Title, 1-sentence pitch ("Transmit 900MHz LoRa frames surprisingly far without a radio"), links to talk + merch, a TOC, then two GitHub alerts: `> [!NOTE]` (license, trademark, ITU region) and `> [!CAUTION]` (harmonics land in banned bands, "virtually no way … could ever pass FCC part 15"). | ~29k chars, very long | 8+ spectrum/waterfall PNGs in the Background section; YouTube thumbnail linked as "video version of this page"; range-test map PNG + table. | Not really — it is a per-folder project index; each subfolder has its own README. | Up front, honest, blunt, in GitHub alert blocks; region note; no false "shielded" claims. | README *is* the writeup; subfolders for code. |
| **gypsum** (codyd51) — homebrew GPS receiver on RTL-SDR. HN 552 pts. https://github.com/codyd51/gypsum | Logo banner, 2 sentences (what + "fix in <60 s from cold start"), screenshot of satellite tracker, hardware needed (RTL-SDR/HackRF + patch antenna), **link to the 4-part writeup**, embedded MP4 of the web dashboard. | ~40 lines. Tiny. | 1 logo, 1 screenshot, 1 inline video. | "Using gypsum": download sample recording → 3 shell commands → run dashboard. Off-the-air replay so anyone can try without hardware. | None (RX only). | The 4-part blog series is the depth; README stays a landing page. |
| **RFHunter** (RamboRogers) — ESP32 + AD8317 RF detector. HN #1, 594 pts. https://github.com/ramborogers/rfhunter | Title, 2-sentence pitch, centered GIF of the device working, link to X video. Then "Updates" (screenshot of being #1 on HN, first "tag from the wild"). | ~120 lines | GIF hero; photos of parts, 3D print, built unit; MP4s in repo root. | BOM (numbered list) → build steps (numbered, with `>` warnings) → flash. | None. | None; README is everything (plus .3mf and .cpp). |
| **Mercury Transforming Drone** (549★) https://github.com/L42ARO/Mercury-Transforming-Drone | Tech-stack badges (RPi, ArduPilot, ESP32…), banner PNG, Buy-me-a-coffee + X badges, Quick Index, **Demo = YouTube thumbnail link**. | ~90 lines | 2×3 HTML table of feature photos with captions. | "Software Setup" after features. | None. | Folder-structure list. |
| **HackRF** (greatscottgadgets) https://github.com/greatscottgadgets/hackrf | Title, 1 sentence, one product photo, author, buy link. | ~35 lines | 1 photo. | None in README; "Documentation → Read the Docs". | None. | Everything on readthedocs. Pure pointer README. |
| **PortaPack Mayhem** https://github.com/portapack-mayhem/mayhem-firmware | Title, 6 badges (nightly, downloads, Discord…), fork lineage sentence, two device photos linked to wiki, "What is this?" = 5 YouTube thumbnails. | ~8k chars | Photos + YouTube thumbs; FAQ sections. | "What to buy?" before "How to install"; install links to wiki. | Commented-out scam warning; nothing regulatory in README (wiki). | Wiki. |
| **rtl_433** https://github.com/merbanan/rtl_433 | Title, 2 paragraphs (what it is, supported SDRs), one screenshot. | ~38k chars (full `-h` output pasted) | 1 screenshot. | Installation = one-liners per OS (`apt`, `brew`, `pkg`). | None. | docs/BUILDING.md, CONTRIBUTING.md, triq.org. |
| **URH** (Universal Radio Hacker) https://github.com/jopohl/urh | Banner image, 6 badges (CI, PyPI, Black Hat Arsenal), dense 1-paragraph pitch with bolded key phrases, "Getting started" = 5 bullet links (install, PDF guide, YouTube playlist, wiki, articles). | ~8k chars | Banner; GIFs further down showing demodulation. | Install per OS after a citation block. | None. | Wiki, PDF userguide, papers. |
| **ESP32 Marauder** https://github.com/justcallmekoko/ESP32Marauder | Centered logo, bold one-line pitch ("A suite of WiFi/Bluetooth offensive and defensive tools for the ESP32"), license/Gitter/Twitter/Instagram badges, CI badges. | ~60 lines | Logo only. | "Getting Started" = download latest release + wiki link. | **FCC module identifiers table** (module FCC IDs per board, careful wording that it's the module grant, not an end-product grant). | Wiki. |
| **Bruce** (ESP32 red-team firmware) https://github.com/pr3y/Bruce | Banner photo, one-sentence pitch, supported boards, promo for their devkit, "How to install" = web flasher link + esptool one-liner. | ~18k chars | Banner; feature list in `<details>` collapsibles. | Web flasher first. | "Disclaimer" at bottom: authorized testing only, no liability. | Wiki + FAQ. |
| **Pwnagotchi** https://github.com/evilsocket/pwnagotchi | Badges (release, license, contributors, Twitter), 1 dense paragraph with links, screenshot of the e-ink face. | ~4.6k chars | 1 UI image. | Links to pwnagotchi.ai docs. | None in README. | External docs site. |
| **Flipper Zero firmware** https://github.com/flipperdevices/flipperzero-firmware | Banner (light/dark `<picture>`), 4 link bullets (site, downloads, user docs, dev docs). | ~6.6k chars | Banner only. | Clone → `./fbt` → `./fbt flash_usb`. | None (they're a certified product). | External docs. Contribution rules ("I need help / I want to…") before build. |
| **ExpressLRS** https://github.com/ExpressLRS/ExpressLRS | Banner, 5 badges, "Support" (donations) first, then Website, About (one dense paragraph), Configurator link, Community, Features bullets, Supported Hardware. | ~5k chars | Banner + community photo. | Points to configurator + website; no CLI. | "We do not manufacture hardware… limited support." | expresslrs.org. |
| **Betaflight** https://github.com/betaflight/betaflight | Logo (light/dark), 4 badges, 1 paragraph mission statement, "This repository holds the firmware". | ~9k chars | Logo. | "Installation & Documentation: see betaflight.com/docs/wiki". | None. | Website. |
| **Meshtastic firmware** https://github.com/meshtastic/firmware | Centered logo + h1, 5 badges + Trendshift badge, Website · Documentation links, 2-paragraph overview, "Get Started" = 2 emoji bullets (build, flash). | ~2.3k chars | Logo + Repobeats stats. | Links only. | None. | meshtastic.org/docs. |
| **ESP-Drone** (Espressif) https://github.com/espressif/esp-drone | Title, language toggle, CI badge, bold-keyword intro paragraph, supported-IDF note, product photo, 4 links (getting started, schematic PDF, iOS/Android app). | ~2.8k chars | 1 photo. | External "Getting Started". | Third-party code license table. | docs.espressif.com. |
| **OpenBCI GUI** https://github.com/OpenBCI/OpenBCI_GUI | Centered screenshot, one-line tagline, "Welcome!" and a TOC; then "What are we doing? / The problem / The solution" bullets. | ~7.5k chars | 1 screenshot. | "Installing" is last in TOC. | None. | docs.openbci.com. |
| **channel3** (cnlohr, ESP8266 analog TV TX) https://github.com/cnlohr/channel3 | Title, one line, "Hook an antenna up to GPIO3/RX, tune your analog TV to Channel 3. Power the ESP on!" then "Background and RF" deep dive. | ~7.4k chars | None in README (video elsewhere). | The one-liner above *is* the quick start. | None (older style). | README is the writeup. |

### B. General dev tools known for great READMEs

| Project | First screen | Pattern worth copying |
|---|---|---|
| **uv** https://github.com/astral-sh/uv | h1, 3 badges, one sentence ("An extremely fast Python package and project manager, written in Rust."), **benchmark bar chart as hero image** with an italic caption, "Highlights" bullets with inline links, then Installation (curl one-liner). | Hero = *proof*, not decoration. Highlights bullets each link into docs. |
| **Ollama** https://github.com/ollama/ollama | Logo, one sentence, **Download** per OS immediately (curl one-liners), then "Get started" = one command. | Install before any explanation; shortest time-to-first-command. |
| **htmx** https://github.com/bigskysoftware/htmx | Logo, italic tagline, 4 badges, intro paragraph, "motivation" = 4 rhetorical questions, "quick start" = 1 script tag + 1 button. | Motivation as questions; quick start is a 6-line snippet that does something visible. |
| **Bun** https://github.com/oven-sh/bun | Centered logo/h1, 3 badges, Docs • Discord • Issues • Roadmap link row, "Read the docs →", "What is Bun?" 2 paragraphs with 4 one-line commands, Install. | Centered link row and `### [Read the docs →]` as a hard pointer to depth. |
| **Zod** https://github.com/colinhacks/zod | Centered logo/h1/tagline/author, 5 badges, link row, "Read the docs →", "What is Zod?" + 12-line code sample, Features bullets. | The first code sample shows the whole value prop in 12 lines. |
| **shadcn/ui** https://github.com/shadcn-ui/ui | ~460 chars: name, one line, screenshot, "Documentation →". | Extreme: README is a billboard, docs site has everything. |
| **tinygrad** https://github.com/tinygrad/tinygrad | Logo, one-line positioning ("between PyTorch and micrograd"), Homepage | Docs | Discord, 3 badges, 4-bullet what-it-is, "How tinygrad compares" (✅/🔁 vs PyTorch/JAX/TVM), then runnable snippets. | Position against known things; comparisons with ✅ marks. |

### C. What the community says (HN threads / guides)

- "Ask HN: How do I improve boring README page?" https://news.ycombinator.com/item?id=26537805 — top answer: what problem it solves and roughly how; **screenshots are mandatory if there's any visual component**, video/asciinema better; name the alternatives honestly; platforms.
- "Ask HN: tips on writing a README" https://news.ycombinator.com/item?id=44081489 — write it early; copy popular repos.
- Show HN retrospectives repeatedly name the above-the-fold demo GIF as the single biggest lever (e.g. https://goshipyard.app/blog/readme-that-gets-you-users, https://repoclip.io/blog/show-hn-demo-video-pattern): one-line pitch at top, visual above the fold, copy-pasteable quickstart; killers are install walls before saying what it is, no visual, vanity badges.
- Regulatory-notice wording examples: LoLRa's `[!CAUTION]` block (above); DEF CON Ham Radio Village fox README leads with "‼️ Read this first: you need a license to transmit" https://github.com/HamRadioVillage/dc34fox; rigflow keeps a separate DISCLAIMER.md https://github.com/dbourgoyne/rigflow/blob/main/DISCLAIMER.md; open-space-sdr has SAFETY_AND_REGULATORY_NOTICE.md https://github.com/open-space-sdr/main/blob/main/SAFETY_AND_REGULATORY_NOTICE.md. FCC background: OET Bulletin 63 https://transition.fcc.gov/oet/info/documents/bulletins/oet63/oet63rev.pdf and 47 CFR Part 15 https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-15.

## Part 2 — patterns that recur

1. **One sentence, then proof.** Every fast-reading README has a ≤25-word pitch directly under the title, then an image that *proves* it (uv's benchmark chart, gypsum's tracker screenshot, RFHunter's GIF). Logos alone (Betaflight, Meshtastic, Marauder) are fine for established brands but tell a newcomer nothing.
2. **Two README species.** *Landing-page* READMEs (gypsum, shadcn, HackRF, Meshtastic: 30–60 lines, everything deep lives elsewhere) and *the-README-is-the-writeup* (LoLRa, channel3, rtl_433: thousands of words). Solo hacker projects that went viral on HN used both — but the landing-page ones (gypsum, RFHunter) paired the short README with a blog/X post that carried the story. Mixing both in one file (LoLRa) works only with a TOC up top.
3. **Quick start within the first ~2 screens**, as copy-pasteable commands (Ollama, uv, Bun, rtl_433, Bruce's web flasher). Hardware READMEs that skip this (HackRF, Betaflight) only get away with it because they have a docs site.
4. **A no-hardware path** is a big multiplier: gypsum ships a recorded I/Q file so you can run it with nothing plugged in; Bruce has a web flasher; esp-drone/Mercury link a demo video. For d8tx the equivalent is "open the web app, see the UI, plug in a DevKit later".
5. **Badges: ≤5, meaningful** (release, CI, license, Discord/downloads). Nobody reading fast parses twelve.
6. **Light/dark `<picture>` hero** is standard now (Flipper, Betaflight, uv, tinygrad).
7. **Legal/RF text placement.** The honest hacker projects put it *early and in a GitHub alert block* (LoLRa `[!CAUTION]`, dc34fox "‼️ Read this first"). Products (Flipper, ELRS) put nothing; attack tools (Bruce) bury a boilerplate disclaimer at the bottom. HN readers respect the LoLRa style (specific numbers, admits what wasn't measured) and mock boilerplate "for educational purposes only".
8. **Deeper docs are one hard pointer**: "Read the docs →" (Bun, Zod, shadcn), "This project comes with a 4-part writeup" (gypsum), "video version of this page" (LoLRa). Not a dozen scattered links.
9. **Hardware photos**: shown as a BOM/parts photo + built-unit photo (RFHunter), a captioned grid (Mercury), or a single product shot (HackRF, esp-drone). Block diagrams are rare in the README itself; they live in the writeup.
10. **Social proof is cheap and used**: RFHunter screenshots its HN #1; Meshtastic embeds a Trendshift badge; URH shows Black Hat Arsenal badges. Fine *after* the quick start, never before.

## Part 3 — recommended skeleton for esp32-d8tx

Target: ≤120 rendered lines; first screen answers "what, proof, is it legal, how do I try it" in under 10 seconds.

```markdown
<picture> light/dark banner OR hero GIF </picture>        # see "Visual assets"
# esp32-d8tx
**Fly a FrSky D8 drone from your browser with a $5 ESP32 DevKit — no radio module, the
chip's own I2S/APLL output is the transmitter.**                     # ≤25 words, bold

[GIF: browser gamepad UI on the left, Tinyhawk lifting off on the right, ~6 s loop]
*Caption: ESP32 DevKit V1 → 2.4 GHz D8 → EMAX Tinyhawk, driven from the web app.*

[release] [CI] [license] [docs/writeup]                          # ≤4 badges
Web app • Writeup • Hardware • Discord/Issues                     # one link row

> [!CAUTION]
> This is a home-built, uncertified transmitter (47 CFR §15.23 framing; D8 lives under
> §15.249). Measured: ~−25 dBm peak EIRP estimated from CC2500 RSSI, ~26 dB below the
> certified EMAX E8; harmonics NOT measured. Only you are responsible for where and
> how you key it. Read [REGULATORY.md] before transmitting.      # true numbers only

## How it works (3 bullets + one diagram)
- Browser/desktop app → WebSerial/USB → ESP32 firmware → I2S bitstream synthesises
  the 2.4 GHz FHSS D8 packets → stock FrSky D8 receiver on the drone.
- [block diagram PNG, ≤800 px wide]
- One sentence on what's *not* done (telemetry? range? bind?).

## Try it in 60 seconds
1. Open <web app URL> (works with any gamepad; no hardware → demo mode shows the UI).
2. Flash the DevKit: `npx esp32-d8tx flash` / web flasher link.
3. Plug in, click Connect, Bind, Arm. [photo: DevKit with the one wire/antenna it needs]

## Hardware you need
Table: ESP32 DevKit V1 · wire antenna length · D8 receiver/drone tested (Tinyhawk) ·
nothing to buy from us (not selling boards/kits/pre-flashed units).

## Read the writeup →   (one hard pointer to the long technical doc, with a 5-bullet TOC:
   D8 protocol RE, generating 2.4 GHz from an ESP32, hopping/timing, link UART limits,
   what was measured and how)

## Status / known limits   (honest bullets; HN rewards this)
## Project layout   (firmware/, packages/, apps/, python/ — one line each)
## Contributing · License · Credits (FrSky D8 reverse-engineering prior art, Betaflight…)
```

### Do / don't

- **Do** lead with the GIF/video of the actual drone flying from the browser; it's the one thing that can't be faked and is what X/HN will embed. gypsum and RFHunter went viral on exactly that asset.
- **Do** put the regulatory block above the fold in a `[!CAUTION]` alert, with real numbers and an explicit "not measured" (LoLRa style). The user has already decided on §15.23 / §15.249 framing and no false test-condition claims — keep it that way; move the long form to `REGULATORY.md` and link it.
- **Do** give a no-hardware path (hosted web app in demo mode) so readers can click something before buying anything.
- **Do** keep the README a landing page and make the writeup a separate doc with a single "Read the writeup →" pointer plus a 5-line TOC so skimmers see the depth exists.
- **Do** position against known things in one line (tinygrad pattern): "like ExpressLRS/Betaflight's world but the TX is a bare ESP32; like LoLRa but for a bidirectional RC link".
- **Do** include a "Status / limitations" section early-ish; HN comments will find them anyway.
- **Don't** open with a wall of badges, a donation ask, or contribution rules (ELRS/Flipper can; a new project can't).
- **Don't** paste CLI `--help` output or the full protocol spec into the README (rtl_433, LoLRa) — link it.
- **Don't** write "for educational purposes only" boilerplate or any claim about shielding/test chambers that didn't happen.
- **Don't** sell anything or hint at kits (Bruce/PortaPack/Marauder do; the owner's stance is explicitly no sales).
- **Don't** exceed ~5 images in the README; put the rest in the writeup.

### Visual assets, in priority order

1. **Hero GIF (or ≤10 s MP4 dropped into the README so GitHub inlines it)**: split-screen — browser/desktop app with gamepad input visible on the left, drone taking off and responding on the right. 600–800 px wide, <8 MB GIF or an MP4. This is the asset for the X post and HN thumbnail; nothing else matters as much.
2. **One block diagram** (browser → serial → ESP32 → RF → receiver → FC), light/dark variants via `<picture>`. Makes "no radio module" click instantly.
3. **One hardware photo**: the bare DevKit with its wire antenna next to the Tinyhawk, on a plain background, so the "$5 board" claim is visible.
4. **One app screenshot** (link/telemetry panel) — optional if the GIF already shows the UI.
5. **One spectrum/waterfall capture** of the D8 hops from the DevKit SDR work — belongs in the writeup, but a thumbnail in "How it works" earns credibility with the RF crowd (LoLRa's README is mostly these).

Everything else (range-test tables, UART timing, decoder plots) goes in the writeup.
