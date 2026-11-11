# Storyboard for SCRIPT.md

This file maps the narration of SCRIPT.md to pictures, scene by scene. SCRIPT.md is split under the same headings (S00 to
S06), so every sentence belongs to exactly one scene file. In every beat table the Narration column quotes SCRIPT.md
exactly, in script order; concatenated, the cells of all tables are the script word for word. Look and motion rules:
STYLE-3b1b.md.

Conventions used below:

- **Reuse** = the object or animation exists today in `common.py`, `parts.py` or the named scene file. **New** = has to be built.
- Colours are the role names in `common.py`: `YELLOW_A` the piece we follow, `ONE`/`ZERO` (blue/red) the two bit values,
  `GREEN_A` receiver / ok, `BLUE_A` transmitter / host, `MUTED` labels, `STRUCT` outlines, `GRID` guide lines, `DIM` = 0.3 opacity.
- Text helpers: `label()` roman, `num()` digits, `mono()` bytes and bits, `caption_at()` bottom caption. Every caption FadeIns
  and FadeOuts; none is written on. Caption text is given in quotes exactly as it should appear.
- The physical-path map strip (`parts.MapStrip`) stays parked at the top edge in every scene except where a beat says
  otherwise. In S00 it does not exist until the end: that scene builds it (beat 14), and from there it is always visible.
- Camera: fixed unless a beat says **view change**. Section 3 lists every camera move and every whole-frame rearrangement
  in the video. Everything else that moves is an object, tied to the words named in the beat. Objects may idle gently (the
  carrier flows, props turn); the camera never moves to fill time.
- Time-like motion (cursor sweeps, the "now" line, packets on a wire) is `linear`; spatial moves are `smooth`.
- One or two numbers per beat. The one piece followed throughout is the throttle: 1150 → 1725 → 0x6bd → bits → tones.
- Identity: the followed packet and the hop plot keep the E8's identity (`42 b2`, hop start 2, step 55, the table
  `common.TABLE`), the cloned ID of `common.BODY`.

## 1. Overview

The script is 1,401 spoken words. At 2.6 words per second the narration alone is 539 s (8 min 59 s). With a 0.3 s lead-in
and about a 1.5 s hold per scene, plus the pauses between voiceover blocks, expect **9 to 10 minutes**. The script's scene
numbers are kept, with letters where a section splits. Eleven scene files, one idea each.

| Scene | File | Script part | Idea | Words | About |
|---|---|---|---|---|---|
| S00 | `s00_intro.py` (new) | S00 | who talks to whom, and what the ESP32 replaces | 149 | 59 s |
| S01 | `s01_key_to_stick.py` (keep, small additions) | S01 | eight control channels, pick the throttle | 64 | 27 s |
| S02a | `s02a_to_esp32.py` (new file; first 60 lines of today's `s02_packet.py` + new) | S02a | the number, its unit, and the wire to the ESP32 | 104 | 42 s |
| S02b | `s02b_packet.py` (rest of today's `s02_packet.py`) | S02b | ticks, the 20 bytes, the packing, the bits | 161 | 64 s |
| S03a | `s03a_fsk.py` (today's `s03_tones.py` rows, first half) | S03a | carrier, frequency, 2-FSK, bit slots | 84 | 34 s |
| S03b | `s03b_gfsk.py` (new) | S03b | how the E8 does it: the glide, and why | 158 | 63 s |
| S03c | `s03c_tones.py` (today's `s03_tones.py` second half, reworked) | S03c | how the ESP32 does it: two test tones | 236 | 93 s |
| S04a | `s04a_hopping.py` (today's `s04_hopping.py`, reworked) | S04a | radio channels, hopping, Wi-Fi, the green bar | 175 | 69 s |
| S04b | `s04b_binding.py` (new; ends with today's S04 stream ending) | S04b | the hop sequence and binding | 115 | 46 s |
| S05 | `s05_drone.py` (keep, SPI picture added) | S05 | the decode, backwards through the same pictures | 115 | 46 s |
| S06 | `s06_recap.py` (new) | S06 | the whole path once more on the map strip | 40 | 17 s |
| | | | **total** | **1,401** | **about 560 s = 9 min 20 s** |

"About" is words ÷ 2.6 plus 2 s per scene for lead-in and end hold.

Shared helpers to add to `parts.py` so that seams and repeated pictures are built once:

| Helper | What it returns | Used by |
|---|---|---|
| `quad_top(scale)` | the top-view quad now drawn inline in S01 | S00, S01, S06 |
| `wire_trace(bits, pitch, center, labels)` | bits-on-a-wire picture: one horizontal trace, high for 1 and low for 0, one slot per bit, slot guides | S02a (UART), S05 (SPI data and clock) |
| `freq_trace(bits, smooth, dev, center)` | frequency-against-time trace for the 8 hero bits; `smooth=0` gives today's step trace (`segs` + `risers` in `s03_tones.py`), `smooth=1` the Gaussian glide; `dev` is the level height | S03a, S03b, S03c, S06 |
| `spectrum_panel(sharp)` | small axes (horizontal "frequency", vertical "strength") with one curve whose width follows `sharp` (0 glide .. 1 jump); curve precomputed with numpy from random-bit FSK, marked illustrative in a code comment | S03b, S03c |
| `margin_block(words, y)` | the small labelled box in the left margin, today's local `block()` in `s03_tones.py` | S03b, S03c |
| `hop_plot(n_done, bar_slot)` | the wide hop plot of S04a with `n_done` packets drawn and the green bar on the lane of slot `bar_slot` | S04a end, S04b start |

## 1b. Decisions in force

Owner decisions: the hop plot uses a true frequency axis (47 channels spread over 2404 to 2477.5 MHz, the E8's hop table
`common.TABLE`); the hero packet keeps the E8's cloned ID; the intro is drawn, no footage; the demo address
`d8tx.mb6611.workers.dev` is on screen in S01; `github.com/mb6611/esp32-d8tx` is on screen at the end of the
recap; the Wi-Fi interference line is spoken as written; eleven scene files.

Why the E8 identity: the ESP32's own identity (experiments/15: `6ff3`, start 205, step 254) puts all 47 hops on every
second channel from 113 to 203, a staircase in a narrow slice of the plot. S04b prints no ID bytes.

Claims worth knowing the basis of: the E8's glide (S03b) is inferred from the CC2500 register settings D8 uses
(`tools/d8-tx-host/d8.py`: MDMCFG2 0x11), not measured on the E8. "The ESP32's signal should be the wider" (S03c) is
expected from theory and not measured; the spectrum curves are illustrative and commented as such in the code. Binding
shares the ID and the hop list; the timing is taken from the packets (S04b beat 7).

## 2. Beat tables

Each row: the exact sentence(s) or clause, what is on screen, what moves and on which words, the caption, and reuse or new.
A sentence split over several rows is quoted in pieces, in order.

### S00 · introduction (`s00_intro.py`, class `S00`, about 59 s)

No map strip at the start: it is built in this scene. Layout for the first half: the E8 at the left (x = −4.5), the drone
at the right (x = +4.5), both at y = 0.6; the lower third (y = −2.0) is a frequency ruler that arrives in beat 6.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "This drone is a Tinyhawk 3." | Top-view quad, 2.2 wide, at x = +4.5. Label `Tinyhawk 3` (`label`, 24) under it. | Quad FadeIns at the start; its four prop circles turn slowly. Label on "Tinyhawk 3". | none | Reuse the S01 quad (move it to `parts.quad_top`). |
| 2 | "It is normally flown with a handheld transmitter, the E8." | Handheld at x = −4.5: `RoundedRectangle` 2.6 × 1.6 (`STRUCT`) with two small gimbal squares inside (the S01 `gimbal()` at scale 0.3, knob dots `BLUE_A`). Label `E8` under it, and under that `the transmitter` (`BLUE_A`, 22). | Outline and gimbals FadeIn on "handheld transmitter"; both labels on "the E8". | none | Gimbals reuse S01; outline and labels new. |
| 3 | "The two talk by radio" | A wavy line from the E8's right edge to the quad's left edge at y = 0.6: the sine shape of the map strip's `air` segment, 12 cycles, `STRUCT`. | `Create` left to right on "talk by radio"; from then on its phase flows toward the drone. | none | Shape from `map_body()`; flowing phase as in S03 (`ph` tracker). |
| 4 | "in a protocol called FrSky D8." | Label `FrSky D8` (`INK`, 28) above the middle of the wave. | FadeIn on "FrSky D8". | none | New label. |
| 5 | "A protocol is an agreed format for messages." | Small yellow blocks (`packet_block(0.8)`) travel along the wave from the E8 to the drone, evenly spaced, all the same size. | First block leaves on "protocol", one every 0.7 s, linear. | "a protocol: the agreed format of the messages" | Reuse `packet_block`. |
| 6 | "In D8 each message is a short packet, a few bytes carrying the stick positions," | One block stops at x = 0 and opens into a small byte row: `packet_row(scale=0.45)` without braces or labels, all cells `DIM`. Label `one packet` above. | On "short packet" the block grows into the row (`ReplacementTransform`). On "stick positions" the knob dots in the E8 move a little and cells 6–17 brighten to full. | "one packet: a few bytes with the stick positions" | Reuse `packet_row`, `dim_row`. |
| 7 | "sent at about 2.4 GHz, the band Wi-Fi uses." | The row closes back into the block, which travels on. Below, at y = −2.0: a horizontal frequency ruler 9 wide, label `frequency` with an arrow at its right end, end ticks `2.40 GHz` and `2.48 GHz`. On it, three wide low humps (`BLUE_DK`, stroke only) labelled `Wi-Fi`, and a row of thin short yellow ticks labelled `D8` across the same span. | Ruler and D8 ticks FadeIn on "about 2.4 GHz"; the Wi-Fi humps draw on "the band Wi-Fi uses". | "about 2.4 GHz: the band Wi-Fi uses" | New. Humps are Wi-Fi channels 1, 6 and 11 (2412, 2437, 2462 MHz, about 20 MHz wide), to scale on the ruler. |
| 8 | "I wanted to fly the drone from my computer," | The E8 and its labels fade to `DIM`. A laptop outline (rectangle 1.8 × 1.1 over a thin base line, `BLUE_A`) appears at x = −4.5, y = −0.2, in front of the dimmed E8; label `computer`. The wave and blocks stop and fade to `DIM`. | Laptop FadeIns on "my computer". | none | New outline. |
| 9 | "without an extra radio module made for D8." | A dashed box 1.3 × 0.6 (`STRUCT`, dashed) labelled `radio module` at x = −2.2, y = 0.6, with a short line from the laptop to it. | Box and line FadeIn on "radio module"; both fade out at the end of the sentence. | none | New, same box style as the map strip's `_box`. |
| 10 | "What I had was an ESP32, a small board with a Wi-Fi radio," | In the same place a solid box 1.5 × 0.9 labelled `ESP32`, and inside it a smaller box labelled `Wi-Fi radio`. A line from the laptop to the box, labelled `USB`. | Outer box on "ESP32", inner box on "Wi-Fi radio"; on "Wi-Fi radio" the three humps on the ruler brighten once. | none | New; the nesting is used again in S03b and S03c. |
| 11 | "so I hacked that radio to speak D8." | The inner box outline turns `YELLOW_A`. The wave is redrawn from the ESP32 box to the drone, and yellow blocks flow along it again. The dimmed E8 fades out. On the ruler the humps dim and the D8 ticks brighten. | Outline changes on "hacked"; wave and blocks on "speak D8". | "the Wi-Fi radio, made to speak D8" | Reuse wave and blocks from beats 3–5. |
| 12 | "That makes the ESP32 a pseudo software-defined radio, or SDR:" | Label under the ESP32 box, two lines: `pseudo` (`YELLOW_A`) and `software-defined radio (SDR)` (`INK`, 22). The ruler fades out. | FadeIn on "software-defined radio". | none | New label; it returns in S03c. |
| 13 | "a radio where software decides what wave goes out." | A small box labelled `software` above the ESP32 box with an arrow down into it. The wave to the drone morphs between three shapes: a plain sine, a faster sine, a sine with a slowly varying height. The blocks are gone. | Box and arrow on "software"; the arrow flashes yellow at each morph; morphs on "decides what wave goes out" (three morphs, 0.8 s each). | "software decides what wave goes out" | New. One `always_redraw` wave driven by a shape tracker. Used again in S03c. |
| 14 | "This one is only partly that, as we'll see." | The wave settles into a plain two-frequency wave (the 8 hero bits, `fsk_wave` stretched to the gap, uncoloured). | Settles on "only partly"; the word `pseudo` does one `Indicate` on "partly". | none | Reuse `fsk_wave`. Flag V3. |
| 15 | "We'll follow one key press all the way to the motors:" | Everything rearranges into the map strip, opened (`focus = 1`): the laptop becomes the `keyboard` and `browser` boxes, the USB line the cable, the ESP32 box the `ESP32` node, the wave the `2.4 GHz` segment, the quad the `drone` group. The SDR label and the `software` box fade out. | Transform on "follow one key press" (1.5 s). The yellow marker appears at `keyboard` there. | none | Reuse `MapStrip`; the transform into it is new. |
| 16 | "through a browser, a USB cable, the ESP32, the air, and the drone." | The opened strip. | The marker steps along once, each named part doing one `Indicate` on its word with the marker on it. After "the drone" the strip closes to the top edge and the marker returns to `keyboard`. | none | Reuse `strip.go`, `strip.close`. |

End frame: the strip parked at the top edge, marker on `keyboard`, nothing else.

### S01 · the app (`s01_key_to_stick.py`, class `S01`, about 27 s)

Start frame: the strip parked, marker on `keyboard`, nothing else (today the page is on screen from frame 0; it has to FadeIn instead).

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "This is the browser app that flies the drone; you can try it at the address on screen." | The simplified Sticks page: two gimbals, the quad, eight bars, the key map. | Page FadeIns on "browser app"; the marker goes `keyboard` → `browser`. The caption FadeIns on "the address on screen" and holds to the end of the sentence. | `d8tx.mb6611.workers.dev` in `mono` | Reuse the page; caption new. |
| 2 | "Everything the pilot controls is a number, called a control channel." | A number above each of the eight bars (`num`, 20): `1000 1500 1500 1500 1500 1500 1000 1500`, each following its bar. | Numbers FadeIn left to right on "is a number". | "a control channel: one number" on "control channel" | New: eight numbers with updaters on the existing `u` tracker. |
| 3 | "There are eight:" | A brace under the eight bars, label `8 control channels`. | Brace grows on "eight". | same caption stays | New brace. |
| 4 | "throttle, yaw, pitch and roll from the two sticks," | The brace goes. | On "the two sticks" both gimbal boxes pulse. On each of the four names its bar pulses and its gimbal knob makes a small move on that axis and comes back: throttle = `THR` (left knob up), yaw = `RUD` (left knob sideways), pitch = `ELE` (right knob up), roll = `AIL` (right knob sideways). | none | Reuse bars and knobs; the four single nudges are new. |
| 5 | "and four auxiliary ones, such as the arm switch." | The four right-hand bars. | The four AUX bars pulse together on "auxiliary". On "arm switch" the `R` key cap lights, the `ARM` bar fills, and its number counts 1000 → 2000. | none | Reuse key caps and bars. Arm = 2000 is the value in the hero packet (`common.CH`). |
| 6 | "Moving the sticks changes all four stick channels at once." | The page. | The existing free stick movement: both knobs move, the quad tilts and turns, the four bars and their numbers change, key caps light. | "all four stick channels move at once" | Reuse. |
| 7 | "Let's follow the throttle." | The other bars dim; the throttle settles at 1150 in yellow. | Existing focus animation, ending on `hero_number()`. | "let's follow the throttle" | Reuse. |

End frame: `hero_number()` (`1150 µs`) centred, strip parked with the marker on `browser`. Same as today.

### S02a · the number and the wire (`s02a_to_esp32.py`, class `S02A`, about 42 s)

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "Pressing W raises the throttle to 1150." | `1150 µs` centred. | `Indicate` on "1150". | none | Reuse. |
| 2 | "That's in microseconds, a convention from servo control pulses:" | Under the number, at y = −1.0: a pulse trace, a low line with three identical rectangular pulses 0.5 high, 3.45 wide, one fully in frame and its neighbours running off both edges (`STRUCT`, the middle pulse `YELLOW_A`). A brace under the middle pulse with the label `1150 µs` (`YELLOW_A`). Label `servo control pulse` (`MUTED`) at the left. | `µs` does one `Indicate` on "microseconds". The trace draws left to right on "servo control pulses". Brace at the end of the clause. | "the number is the length of a pulse" | New. Scale: 3 units per 1000 µs, so the pulse rises at x = −4.5 and falls at x = −1.05. |
| 3 | "1000 is off and 2000 is full power." | Two dashed ghost falling edges on the middle pulse: one at 1000 µs (x = −1.5), one at 2000 µs (x = +1.5), labelled `1000: off` and `2000: full power`. Then the stretch between the two ghosts becomes the gauge line. | Ghost at 1000 on "1000 is off", ghost at 2000 on "2000 is full power". Then the segment between them stretches into today's gauge (line from x = −4 to +4 at y = −1.7), the two labels ride to its ends, and the pulse's own falling edge becomes the yellow marker dot at x = −2.8. The rest of the trace fades. | none | Gauge, labels and marker are reuse; the transform into them is new. |
| 4 | "So 1150 is a gentle 15 %." | Gauge with the marker at 15 %. | `15 %` label FadeIns above the marker on "15 %". | none | Reuse. |
| 5 | "D8 sends one packet about every 9 ms, a bit over a hundred a second." | The gauge fades. In its place a time line at y = −1.7, 11 wide, ticks every 1.1, label `time` with an arrow at the right. A small yellow block on each tick. A brace between two ticks: `about 9 ms`. | Blocks appear one after another left to right, linear, starting on "one packet". Brace on "9 ms". Label `a bit over 100 a second` at the right on those words. | none | New time line; blocks are `packet_block(0.7)`. |
| 6 | "The ESP32 keeps that pace," | Same. Label `ESP32` at the left end of the time line. | A highlight runs along the blocks left to right, one per 0.25 s. | none | New. |
| 7 | "and the browser sends it all eight values just as often, down the USB cable." | `1150` becomes part of the serial line `S 1150 1500 1500 1500 1500 1500 2000 1500` (yellow `1150`), centred at y = 0. A second row of ticks above the time line, labelled `browser`, each with a short white dash that lines up with a block below. Then the strip opens and the marker runs `browser` → `ESP32` along the cable, repeatedly. | Line forms on "all eight values"; dashes appear on "just as often"; strip opens and the marker runs on "down the USB cable". The time line fades when the strip opens. | "one line of eight values, every 9 ms" | Reuse the line, `strip.open`, the repeated `strip.go(K_ESP)`. Second tick row new. |
| 8 | "On the board, a small chip turns USB into a serial connection called UART:" | Strip open, marker resting on the cable. A small box at the ESP32 end of the strip's cable, labelled `USB to UART chip` (`MUTED`; it is a CP2102). `UART` (`INK`) sits between that box and the `ESP32` node. The serial line below. | Box on "a small chip"; `UART` FadeIns on "called UART". | none | New box and label. |
| 9 | "bits on a wire, one after another," | The first yellow character of the line, `1`, lifts out and shows its eight bits under it in `mono`: `1 0 0 0 1 1 0 0` (the character `1` is 0x31, sent lowest bit first). The bits become a wire trace at y = −1.6: one horizontal line that sits high for a 1 and low for a 0, one slot of 0.9 per bit, `ONE`/`ZERO` colours, with a dim low slot in front and a dim high slot behind (start and stop, not labelled). Labels at the left: `high = 1`, `low = 0`. Tags `chip` at the left end, `ESP32` at the right end. | Character lifts on "bits on a wire". Each bit digit drops into its slot and the trace draws left to right on "one after another", linear; a small dot rides the trace. | "UART: bits on a wire, one after another" | New: `parts.wire_trace`. |
| 10 | "at a speed both ends have agreed on." | Thin slot guides at every bit edge. A brace under one slot: `about 1 µs`. Under each tag a short comb of ticks with the same spacing as the slots. | Guides on "a speed"; the two combs pulse together on "both ends have agreed on". | "both ends count the same time per bit" | New. 921600 baud is 1.085 µs per bit (`protocol/PROTOCOL.md`). |
| 11 | "The ESP32 builds a D8 packet from the values." | The trace folds back into the line, the line into `1150 µs`. Strip closes with the marker on `ESP32`. | Fold on "the values"; `Indicate` on `1150` at the end. | none | Reuse (`piece` → `hero2`, `strip.close`). |

End frame: `hero_number()` centred, strip parked with the marker on `ESP32`.

### S02b · into the packet (`s02b_packet.py`, class `S02B`, about 64 s)

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "D8 counts in smaller ticks, one and a half to a microsecond," | `1150 µs`. Under it at y = −1.6, two short rulers of the same length (3.0), one above the other: the upper divided in 2 cells, brace over one cell `1 µs`; the lower divided in 3 cells, label `ticks` at its right. | Upper ruler on "microsecond" (end of the clause, with the `µs` of the number pulsing once). Lower ruler on "smaller ticks"; on "one and a half" a bracket marks one and a half lower cells under one upper cell. | "1 µs = 1.5 ticks" | New. |
| 2 | "so each value is multiplied by 1.5, and 1150 becomes 1725:" | `1150 × 1.5 = 1725`, then the unit label `ticks` after 1725. | Existing `× 1.5` and `=` animation on "multiplied"; `1725` on "1725"; the `ticks` label arrives with it. Rulers fade. | none | Reuse; the `ticks` label is new. |
| 3 | "the same throttle in a smaller unit." | The gauge from S02a returns at y = −1.7 with its marker at 15 %. Its end labels change from `1000` / `2000` with unit `µs` to `1500` / `3000` with unit `ticks`. | Gauge FadeIns on "same throttle". The end labels change on "smaller unit". The marker does not move. | "same position, smaller unit" | Reuse the gauge; the label change is new. |
| 4 | "In hex that is 6BD: three hex digits, which is 12 bits." | `1725` → `0x6bd`. Under the three hex digits, three groups of four bits in `mono`: `0110 1011 1101`, a small brace under each group. | Existing hex transform on "6BD". Bit groups appear under their digits one by one on "three hex digits"; label `12 bits` under them on "12 bits". Gauge fades. | "1725 in hex: a 12-bit value" | Reuse transform and caption; bit groups new. |
| 5 | "A D8 packet is 20 bytes." | The bracketed 20-byte row. | Existing row build. | "one D8 packet: 20 bytes" | Reuse. |
| 6 | "A length byte." | Cell 0 lit, brace label `length`. | Existing. | none | Reuse; `GROUPS` label "header" → "length". |
| 7 | "The transmitter's two-byte ID, so the drone only listens to its own transmitter." | Cells 1–2 lit, brace `ID`. | Existing. | none | Reuse. |
| 8 | "Three bookkeeping bytes, one of them a counter that numbers the packets." | Cells 3–5 lit, brace label `bookkeeping`. Under cell 4 a small label `counter` and, beside it in dim `mono`, `00, 01, 02, …`. | Brace on "three bookkeeping bytes"; cell 4 pulses and its label appears on "a counter". | none | Reuse the brace; `GROUPS` label "counter" → "bookkeeping"; the cell-4 label is new. Byte 4 is the counter (`packet.h` `d8_build_body`). |
| 9 | "The eight control channel values, in 12 bytes." | Cells 6–17 lit, brace label `8 control channels`; a count `12 bytes` under the brace. | Existing; the count on "12 bytes". | none | Reuse; `GROUPS` label "8 stick values" → "8 control channels". |
| 10 | "And a two-byte checksum, so the receiver can check that nothing got corrupted in the air." | Cells 18–19 lit, brace `checksum`. | Existing checksum beat: the brace on "two-byte checksum", the cells pulse on "nothing got corrupted". | none | Reuse. |
| 11 | "Twelve bits is a byte and a half, so D8 splits each value." | `0x6bd` over the row; `6` and `bd` separate. | Existing; the split on "splits". | "12 bits: one byte and a half" | Reuse. |
| 12 | "The low 8 bits, BD, get a byte of their own." | `bd` flies into cell 6. | Existing. | "the low 8 bits fill one byte" | Reuse. |
| 13 | "The top 4 bits, the 6, share a byte with the top 4 of the next channel." | `6` flies into the low half of cell 10; the next channel's `8` fills the other half. | Existing, two steps. | "the top 4 bits take half of another", then "the next channel fills the other half" | Reuse; "stick" → "channel" in the second caption and in the `next stick` label. |
| 14 | "So eight channels fit in 12 bytes instead of 16." | Cells 6–17. | Existing. | "8 channels fit in 12 bytes, not 16" | Reuse; "sticks" → "channels". |
| 15 | "Written out, the 20 bytes are 160 ones and zeros." | The row unrolls into 160 bit squares. **View change 1**: the camera moves in on the throttle's eight bits (width `UZOOM_W`). | Existing. | "the packet, as 160 ones and zeros" | Reuse. |

End frame: `bit_cells()` seen at `UZOOM_W`, the throttle's bits lit. Same as today.

### S03a · carrier and 2-FSK (`s03a_fsk.py`, class `S03A`, about 34 s)

Layout is today's S03: the eight throttle bits at y = 2.4, row 1 (frequency trace) at y = 1.3, row 2 (carrier) at y = 0,
row 3 (the sum) at y = −1.5, all 10.4 wide. Row 1 gets an axis title at its left end, rotated: `frequency`; and `time` with
an arrow under row 3 at the right. No numbers on row 1 in this scene: 32 and 39 kHz belong to S03b and S03c.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "Now those bits have to get into the air." | The eight throttle bits spread to full width; the other bits fade. | Existing. | none | Reuse. |
| 2 | "A radio signal is built around a carrier: a steady wave at one frequency," | Row 2: the carrier, label `carrier` at its right. A dot at the left end of the carrier rides the wave up and down as it flows. | Existing `Create`, then the wave flows (`ph` tracker). Dot FadeIns on "one frequency". | "the carrier: a steady wave at one frequency" | Reuse. New: a dot on the existing `carrier_ph`. No `channel A` / `2.404 GHz` label: radio channels are not introduced until S04a. |
| 3 | "here about 2.4 GHz, or 2.4 billion swings a second." | A brace over one cycle at the left: `one swing`. Under the `carrier` label: `about 2.4 GHz`, and under that `2,400,000,000 swings a second` (`MUTED`, 20). | Brace and dot-ride on "swings"; first label on "2.4 GHz", second on "2.4 billion". | none | New labels. |
| 4 | "D8 sends bits by shifting that frequency:" | Row 2. | On "shifting" the carrier squeezes once and stretches once (`cyc` 3 → 4 → 2 → 3, 1.6 s). The brace and the second label line fade. | "the bits shift the carrier's frequency" | Reuse the `cyc` tracker. |
| 5 | "a little up for a 1," | Row 1: dashed centre line with label `centre` at the right; the upper level segments for the 1 bits (`ONE`), label `a little higher` (`ONE`). | Existing: the 1 segments drop in and the carrier squeezes. | same caption stays | Reuse; label text changed from `+39 kHz`. |
| 6 | "a little down for a 0," | The lower segments (`ZERO`), label `a little lower`. Risers appear. | Existing. | same caption stays | Reuse. |
| 7 | "each bit in its own slot of time." | Thin dashed guides (`GRID`) at every bit edge, from the bit squares down through row 3. Row 3 appears with `+` and `=`. A brace under the first slot of row 3: `one bit`. | Guides appear left to right on "its own slot". | none | New guides; brace is today's `b0` with a different label. |
| 8 | "This is frequency-shift keying, or FSK; with two frequencies, 2-FSK." | Rows 1–3. | On "frequency-shift keying" the cursor sweep runs: the dashed cursor crosses the eight bits (0.4 s per bit, linear), the dot on row 1 hops between the two levels, row 3 colours in behind the cursor, each bit square fills as it is passed. On "2-FSK" the upper level pulses, then the lower. | "frequency-shift keying (FSK)", then "two frequencies: 2-FSK" | Reuse the sweep; captions new. |
| 9 | "The real shift is far too small to see, so the picture exaggerates it." | Note under row 3. Sweep done, cursor gone. | Note FadeIns on "exaggerates". | note: "wave exaggerated" | Reuse. |

End frame: bits, row 1 step trace with `a little higher` / `a little lower`, carrier, coloured row 3, slot guides, no
caption, cursor gone, wave phase at rest.

### S03b · how the E8 does it (`s03b_gfsk.py`, class `S03B`, about 63 s)

The E8 is not on the map strip, so the strip fades to `DIM` for this scene and comes back in S03c. That is the only time
the strip dims, and it is tied to "The E8 has a radio chip".

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "The E8 has a radio chip built for FSK." | Block `E8` in the left margin at row-2 height (x = −6.1), with a smaller inner box `radio chip`. | Block FadeIns on "The E8" and the strip dims; the inner box on "radio chip". | none | Reuse `block()` as `parts.margin_block`; nesting as in S00 beat 10. |
| 2 | "It hands the chip the packet's bytes," | Four small byte cells (from `packet_row`, scale 0.4; the yellow `bd` among them) slide from the top left into the block. | Cells slide in on "the packet's bytes". | none | Cells reuse. |
| 3 | "and for each bit the chip moves the frequency about 32 kHz up or down." | The arrow from the block to the rows lights yellow. Row 1 labels change to `+32 kHz` (`ONE`) and `−32 kHz` (`ZERO`). | Arrow on "for each bit"; label change on "32 kHz"; row 3's wave pulses once. | none | Reuse arrow (`arrow()` in `s03_tones.py`) and labels with new text. Stock deviation is 31.7 kHz (`tools/d8-tx-host/d8.py`). |
| 4 | "Each bit lasts 32 µs, about 31,000 bits a second." | The `one bit` brace label becomes `32 µs`. | Label change on "32 µs". | "about 31,000 bits a second" on those words | Reuse (`t32`). |
| 5 | "With D8's settings, the chip doesn't jump between the two frequencies." | Rows 2 and 3 and the bit squares fade to `DIM`. Row 1 grows to three times its height, centred at y = 0.6 (levels at ±0.85). | Row 1 grows on "doesn't jump"; its risers flash once on "jump" and then fade to `DIM`. | none | New: row 1 is `parts.freq_trace` so it can be scaled and smoothed. No camera move. |
| 6 | "It glides." | The step trace becomes a smooth one: flat near each level, an S-shaped move through every bit edge. | Transform on "glides" (1.2 s); a dot then rides the trace across the first three bits, linear. | "the frequency glides" | New: `freq_trace(smooth=1)`. |
| 7 | "The smoothing has a bell-curve shape, a Gaussian, so this is Gaussian FSK, or GFSK." | A small bell curve (`YELLOW_A`, 0.9 wide) above the first bit edge. The sharp trace is kept behind as a `DIM` ghost. | The bell appears on "bell-curve"; it slides along the trace from the first edge to the last on "Gaussian", pausing a beat at each edge. | "Gaussian FSK (GFSK)" on "GFSK" | New. |
| 8 | "Still two frequencies, one bit at a time; only the move between them is smooth." | Row 1 enlarged, smooth. | The two dashed level lines pulse on "two frequencies"; the slot guides pulse on "one bit at a time"; the curved stretches at the bit edges turn yellow for a moment on "the move between them". | none | New highlights. |
| 9 | "Why glide?" | Row 1 shrinks back to y = 2.0 at its normal size (still smooth). Rows 2 and 3, the bits, and the margin block fade out. Two empty panels appear below: left (x = −3.4, y = −0.9, 5.6 × 2.6) titled `the wave over time`; right (x = +3.4, same size) with a horizontal axis `frequency` and a vertical axis `strength`. | Rearrangement on "Why glide?" (1.2 s). | none | New: right panel is `parts.spectrum_panel`. |
| 10 | "A steady wave sits at exactly one frequency." | Left: a steady sine. Right: one thin vertical spike at the centre. | Sine draws on "steady wave"; spike grows on "exactly one frequency". | none | New. |
| 11 | "A sudden change is made of many frequencies at once," | Left: the sine now changes frequency abruptly at its middle (slow half, fast half). Right: the spike becomes a hump with low skirts on both sides; two small arrows under the hump pointing outward. | Left changes on "A sudden change"; skirts lengthen outward on "many frequencies at once"; arrows on "at once". | "a sudden change spreads over many frequencies" | New. Left wave from `fsk_pieces` with two bits. |
| 12 | "and the sharper the change, the wider they spread." | Left: the change at the middle of the wave goes from gradual to abrupt and back, twice. Right: the hump's skirts narrow and widen in step. | One sweep on "the sharper the change", one on "the wider they spread" (each 1.5 s, there and back). Ends on abrupt and wide. | same caption stays | New: one `sharp` tracker drives both panels. |
| 13 | "Fourier analysis explains why; we won't go into it." | Between the panels, an arrow from left to right with the label `Fourier analysis` (`MUTED`). | Label FadeIns on "Fourier analysis" and fades to `DIM` on "we won't go into it". Nothing else moves. | none | New. Flag V1. |
| 14 | "So a signal that jumps leaks into neighbouring frequencies, where other radios may be listening." | Right panel: two dashed vertical lines split the axis into three bands, labelled under the axis `neighbour`, `our signal`, `neighbour`. The parts of the skirts inside the neighbour bands are filled `RED_A` at 0.4. A small green tick in each neighbour band. | Band lines on "a signal that jumps"; red fill on "leaks"; green ticks on "other radios may be listening". | "a signal that jumps leaks into its neighbours" | New. |
| 15 | "Gliding keeps it narrow." | `sharp` goes to 0: left wave changes gradually, right hump narrows, the red fill shrinks to nothing. Row 1 above pulses once. | On "narrow". | "gliding keeps the signal narrow" | New. |
| 16 | "The smoothing is for the neighbours, not the receiver." | The two panels fade out. Row 1 moves to y = 0.6 enlarged again; the eight bit squares return at y = 2.4. On row 1, a dot at the centre of each slot, on the trace: `ONE` where the trace is above the centre line, `ZERO` where it is below. A thin line from each dot up to its bit square. | The two `neighbour` labels pulse on "the neighbours" before the panels fade; the rearrangement runs on "not the receiver"; dots appear left to right, each bit square pulsing as its dot appears. | "the receiver asks: above the centre, or below?" | New: slot-centre sample dots. Used again in S03c and S05. |
| 17 | "The drone can read plain 2-FSK without it." | The smooth trace becomes the step trace again. The dots stay where they are and keep their colours. | Transform on "without it"; the dots and the bit squares pulse together on "plain 2-FSK". | "plain 2-FSK: the same bits" | New. |

End frame: bits at y = 2.4; row 1 enlarged at y = 0.6 as a step trace with `+32 kHz` / `−32 kHz`, its sample dots and
slot guides; nothing else; strip `DIM`.

### S03c · how the ESP32 does it (`s03c_tones.py`, class `S03C`, about 93 s)

Layout from beat 1: row 1 enlarged stays at y = 0.6; row 3 (the wave, amplitude 0.45) returns at y = −1.6; the margin
block sits at x = −6.1, y = −0.5. Row 2 (the bare carrier) is not shown again.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "The ESP32's Wi-Fi radio works in the same band and can tune its carrier where we want." | Margin block `ESP32` with inner box `Wi-Fi radio`. The strip returns to full opacity, marker on `ESP32`. Row 1's trace, its dots and labels stay but dim to `DIM` on "Wi-Fi radio". Row 3: a steady uncoloured carrier at y = −1.6, label `about 2.4 GHz` at its right. An arrow from the block to the carrier. | Block on "Wi-Fi radio"; carrier draws and flows on "the same band"; arrow lights yellow and the carrier squeezes a little, stretches a little, and settles (`cyc` 3 → 3.5 → 2.5 → 3) on "tune its carrier". | none | Reuse block, `carrier_ph`, `cyc`. |
| 2 | "But it is built for Wi-Fi and Bluetooth." | Two small tags under the block: `Wi-Fi`, `Bluetooth` (`MUTED`). | Tags appear on their words. | none | New tags. |
| 3 | "Copying the glide would take an arbitrary signal, any wave we choose, which is hard to get out of it." | Row 1: the E8's smooth trace as a dashed `MUTED` ghost, label `the E8's glide`. The carrier morphs through the three shapes of S00 beat 13. Then a small red cross on the arrow from the block and the carrier returns to a plain sine. | Ghost on "Copying the glide"; morphs on "any wave we choose"; cross on "hard". | "an arbitrary signal: any wave we choose" | Reuse `freq_trace(smooth=1)` and the S00 morph; the cross from today's CPU beat. |
| 4 | "But it has an undocumented test feature, a test tone:" | A second inner box in the block: `test tone`, thin `YELLOW_A` outline. The cross and the ghost fade. | Box on "test feature". | none | Reuse today's `tone generator` block with new text. |
| 5 | "one steady wave at a single frequency," | Row 1: one flat line at the centre level (`INK`). Row 3: the steady sine. | The flat line draws on "a single frequency"; the arrow from the block lights. | "the test tone: one steady frequency" | New flat line in `freq_trace` style. |
| 6 | "offset from the carrier in steps of about 39 kHz," | Row 1: faint dashed rungs at −3 … +3 steps (0.34 apart), small numbers at the right `+2 +1 0 −1 −2`. A brace between rungs 0 and +1: `about 39 kHz`. | Rungs on "offset from the carrier". On "in steps" the flat line steps 0 → +1 → +2 → +1 → 0 → −1 → 0 (0.35 s each) and the sine in row 3 squeezes and stretches with it. Brace on "39 kHz". | same caption stays | New. One step is 40 MHz / 1024 = 39.06 kHz (`firmware/main/d8tone.c`). |
| 7 | "about 1 part in 60,000 of the carrier." | Under the `about 39 kHz` brace: `about 1 part in 60,000 of the carrier` (`MUTED`). The flat line rests on rung 0. | Label on "1 part in 60,000". | none | New. 39.06 kHz / 2.4 GHz = 1 in 61,500. |
| 8 | "And D8 doesn't need an arbitrary signal." | Same. | Nothing moves. Still frame. | none | Flag V5. |
| 9 | "The receiver only asks whether the frequency is above the centre or below." | Row 1: the half above the centre line gets a faint `ONE` tint with the label `above: 1`; the half below a faint `ZERO` tint with `below: 0`. | Centre line pulses on "the frequency"; upper tint on "above", lower on "below". | "above the centre, or below?" | New tints. |
| 10 | "So two tones are enough: one step above for a 1, one step below for a 0." | The rungs other than +1 and −1 fade out, with their numbers. Rung +1 turns `ONE` with label `+39 kHz`; rung −1 turns `ZERO` with `−39 kHz`. The step trace for the hero bits forms on the two rungs. The bit squares are still at y = 2.4. | Rungs on "two tones"; the 1 segments drop onto the upper rung on "one step above for a 1", the 0 segments onto the lower on "one step below for a 0". | "two tones: one step above, one step below" | Reuse `segs` drop-in. |
| 11 | "That's 39 kHz where the E8 uses 32, which makes no difference to that question." | Two thin dashed `MUTED` lines just inside the rungs (at 32/39 of their height), label `E8: 32 kHz` at the left. The slot-centre dots of S03b return on the trace, same colours, with their thin lines up to the bit squares. | Lines on "the E8 uses 32"; dots left to right on "no difference"; bit squares pulse on "to that question". The E8 lines and the tints fade at the end. | none | New lines; reuse the S03b dots. |
| 12 | "Software switches the radio between the two tones, one bit every 32 µs." | A box `software` above the margin block with an arrow into `test tone`. The cursor sweep: dashed cursor across the eight bits, a dot hopping between the two rungs, row 3 squeezing and stretching and colouring in behind the cursor. Brace under the first slot: `32 µs`. | `software` box on "Software"; sweep starts on "switches" (0.4 s per bit); the arrow from `software` flashes at every bit edge where the tone changes. | "one tone or the other, 32 µs at a time" | Reuse the sweep, `b0`/`t32`; `software` box as in S00. |
| 13 | "Software picks which tone goes out, and when: that is the software-defined part." | Tag under the margin block: `software-defined radio` (`INK`, 20). | Tag on "software-defined". The `software` box pulses on "Software picks"; the dot repeats its hops along the rungs at double speed on "which tone goes out, and when". | none | Reuse the S00 label text. |
| 14 | "It has only these tones, not any wave: that is the pseudo part." | The dashed ghost of the E8's glide flashes in row 1 at `DIM` with the red cross, then goes. The word `pseudo` (`YELLOW_A`) appears in front of the tag. | Ghost and cross on "not any wave"; the two rungs pulse on "only these tones"; `pseudo` on "pseudo part". | none | Pays off S00 beat 14. |
| 15 | "So the E8's frequency glides and the ESP32's jumps." | Rearrangement into four rows under the bits, all sharing the slot guides. Row labels at the left. `E8` trace (smooth, ±32) at y = 1.35; `E8` wave at y = 0.45; `ESP32` trace (steps, ±39) at y = −0.75; `ESP32` wave at y = −1.65. Trace rows 0.5 high, waves amplitude 0.32. Margin block, `software` box and tags fade out. | Rearrangement on "So" (1.2 s). Then one cursor sweeps all four rows; a dot rides each trace: the upper one curves, the lower one jumps. "glides" and "jumps" fall inside the sweep. | "E8: glides. ESP32: jumps." | New layout; all four rows are existing helpers (`freq_trace`, `wave_ph`). The E8 wave is drawn from the smooth frequency. |
| 16 | "The ESP32's signal should be the wider of the two, though I haven't measured it." | The two wave rows fade out. In their place one spectrum panel at y = −1.2 (8 × 2.2): a narrow curve labelled `E8` (`INK`) and a wider, lower-skirted curve labelled `ESP32` (`YELLOW_A`), same centre. | E8 curve on "The ESP32's signal"; ESP32 curve grows outward on "the wider"; the caption on "haven't measured it". | "expected: a wider signal (not measured)" | Reuse `spectrum_panel`. Illustrative curves, commented as such in the code. |
| 17 | "The drone reads the same bits from both." | The panel fades. Slot-centre dots on both traces; thin lines from both up to the one row of bit squares. | Dots on both traces together, left to right, on "the same bits"; squares pulse on "from both". | "the same bits from both" | Reuse dots. |
| 18 | "In the air, a short fixed pattern goes in front of the packet, so the receiver can find its start." | **View change 2** (no camera, a redraw): the E8 rows and the bits fade out; the ESP32 wave shrinks into a thin strip that stands for the whole packet: a bar 8.8 wide and 0.5 high at y = 0 holding 160 bit ticks (`PBITS`, `ONE`/`ZERO` at 0.4), the throttle's bits full yellow, brace above `the packet: 20 bytes`. A second bar 2.64 wide (48 ticks from `AIR_HEAD`, the first 32 visibly alternating) slides in at its left, `GREEN_A` outline, label `fixed pattern` above. | Packet bar forms on "In the air"; the pattern bar slides in from the left on "a short fixed pattern goes in front". A thin green vertical line sweeps the pattern left to right and stops at the boundary on "find its start"; label `the packet starts here` under it. | "the same pattern before every packet" | New bar; `AIR_HEAD` and `PBITS` exist. 0.055 per bit, 208 bits = 11.44 wide. |
| 19 | "One packet is one short burst of this wave, about 7 ms long." | A brace under both bars: `about 7 ms`. Then a yellow box around both bars becomes the packet block. | Brace on "about 7 ms". Box and the existing transform into `packet_block_big()` at the end of the sentence. | "one packet: one burst, about 7 ms" | Reuse the box → block transform. 208 bits × 32.2 µs = 6.70 ms. |

End frame: `packet_block_big()` centred, strip parked with the marker on `ESP32`. Same as today.

### S04a · radio channels and hopping (`s04a_hopping.py`, class `S04A`, about 69 s)

This scene has two views and one camera move between them.

**Close view** (start, same as today): camera width `CLOSE_W` on the packet block. Lanes are neighbouring radio
channels, one lane (0.25) per channel number, so the block sits in lane 57 with 56 and 58 beside it.

**Wide view**: one fixed camera for the rest of the scene. The plot is 18 time slots wide (slot = `SLOT_W` = 0.7, so 12.6)
and holds every channel number from 0 to 246 in its height (7.4, so 0.03 per channel). Camera width 18, centred on the
plot, shifted so the plot's left edge leaves room for the vertical axis title. A packet keeps the size it has in the close
view (`PKT_W` × `PKT_H`), which is about seven channel numbers high at this scale; that is deliberate so it stays visible.
Slot s carries channel `TABLE[1 + s]` (the E8's table, `common.TABLE`): 57, 112, 167, 222, 21, 76, 131, 186, 241, 40, 95,
150, 205, 4, 59, 114, 169, 224. Channel n is at 2404 MHz + n × 299.93 kHz, so the 47 channels (0 to 245) spread over 2404
to 2477.5 MHz.

Axes in the wide view: horizontal arrow under the plot with `time`; a brace under the first slot, `about 9 ms`. Vertical
arrow at the left with `frequency`, and three tick labels on the left edge: `channel 0` (bottom), `channel 100`,
`channel 200`; at the bottom and top of the axis in `MUTED`: `2.404 GHz`, `2.478 GHz`.

The green bar: a `Rectangle` one lane high (0.25 in plot units, slightly taller than a packet) and as wide as the whole
plot, `GREEN_A` stroke, `GREEN_A` fill at 0.2. A tag `RX` (`GREEN_A`) sits just outside its right end and a tag `TX`
(`BLUE_A`) with a small pointer sits just outside its left end; both tags stay at the bar's height.

The "now" line: a thin vertical `MUTED` line over the plot's full height that moves right at constant speed. A packet
draws itself from left to right as the line crosses its 0.75 of a slot.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "The burst leaves the ESP32's antenna around one carrier frequency." | Close view. The packet block; the local grid around it; axis words `time` (with arrow, below) and `frequency` (with arrow, left). A dashed horizontal line through the block's middle, label `its carrier` at the right end. | Strip opens, marker `ESP32` → `2.4 GHz`, strip closes on "leaves the ESP32's antenna". Grid and axis words FadeIn on "around"; dashed line on "one carrier frequency". | "out of the antenna, into the air" | Reuse `patch`, `lab_t`, `lab_c`; dashed line new. |
| 2 | "The band is divided into numbered radio channels, 300 kHz apart, each a narrow band of frequencies with a carrier at its centre." | Five lanes, numbered at the left edge `55 56 57 58 59` (`MUTED`, 57 in `INK`). A brace at the right between the centres of lanes 57 and 58: `300 kHz`. Lane 57 outlined in `INK` (thin), the dashed carrier line through its middle. | Lane numbers appear bottom to top on "numbered radio channels"; brace on "300 kHz apart"; outline on "a narrow band of frequencies"; the dashed line pulses on "carrier at its centre". | "a radio channel: a narrow band of frequencies" | Reuse `patch(nl=2)`; numbers, brace, outline new. Channel n = 2404 MHz + n × 299.93 kHz (`packet.h` `d8_channel_f10`). |
| 3 | "On another radio channel the carrier is different, so the wave is different, but it carries the same bits." | Still the close view. The block in lane 57 opens into its wave strip (`fsk_wave(cyc=3)`, hero bits coloured); a second strip appears in lane 59 (`cyc=4`, same colours), labels `channel 57`, `channel 59`. | Second strip on "another radio channel"; the upper strip pulses on "the wave is different"; both colour patterns pulse together on "the same bits". Then the second strip fades and the first closes back into the block. | "another channel, the same bits" | Reuse `fsk_wave`. |
| 4 | "D8 doesn't stay on one radio channel." | **View change 3**: the camera pulls back to the wide view while the lanes compress vertically from 0.25 to 0.03 per channel, so the whole band comes into frame. The lane lines fade as they crowd; the lane numbers, the outline and the 300 kHz brace fade; the wide-view axes fade in. The block keeps its size and stays on channel 57 at slot 0. | Starts on "doesn't stay", 2.0 s, smooth. | none | New: one tracker for the lane height, used by the block's position. |
| 5 | "Each packet goes out on a different one, about 9 ms after the last." | Wide view. The now line starts at the right edge of packet 0. | The now line crosses slot 1; packet 1 draws on channel 112, then slot 2 (167). A thin yellow arrow from each packet to the next grows as it lands. The `about 9 ms` brace pulses on "9 ms". 1.0 s per slot. | "next packet: another radio channel" | Arrow reuse (`arrows` in today's S04); now line new. |
| 6 | "This is frequency hopping." | Same. | Slots 3–5 at the same pace: 222, then the long drop to 21, then 76. | "frequency hopping" | — |
| 7 | "D8 hops across 47 radio channels, spread over the band." | Short dashes on the right edge of the plot at the heights of all 47 channels in the list, spanning the whole axis from `2.404 GHz` to `2.478 GHz`; a brace beside them: `47 radio channels`. | The now line speeds up (0.3 s per slot) through slots 6–17 while the dashes appear; brace on "47". The now line stops at the right edge. | none | New dashes; brace reuse. |
| 8 | "Hopping protects the link." | The plot with 18 packets and their arrows. | A highlight runs along the arrows from packet 0 to packet 17 (1.5 s). Otherwise still. | none | Flag V2. |
| 9 | "A Wi-Fi network sits on about a dozen of the 47 radio channels," | A red band across the whole plot from channel number 77 to 143 (Wi-Fi channel 6, 2427 to 2447 MHz, 20 MHz wide), `RED_A` at 0.25, label `Wi-Fi network` at its right. It is 2.0 plot units high of 7.4. The 12 dashes inside it (78, 80, 95, 97, 99, 112, 114, 116, 118, 131, 133, 135) turn red. | Band draws left to right on "Wi-Fi network"; the 12 dashes turn red on "about a dozen". | "a Wi-Fi network: about 12 of the 47 radio channels" | New band; reuse `noise`. |
| 10 | "so packets sent there can interfere with it if both are sent at the same time." | Short `RED_A` Wi-Fi bursts appear in the band at slots 6 and 15 (the same time as packets 6 and 15, channels 131 and 114), each as wide as a slot. Packets 1 and 10 (channels 112 and 95) are in the band, but no burst is there. | Bursts flash on "at the same time"; packets 6 and 15 get a jagged red overlap outline and fade to `DIM`. Packets 1 and 10 pulse once, unharmed, on "can interfere". | "in the band, and at the same time: they interfere" | New. Interference is shown only where both are on air at once, as the sentence says. |
| 11 | "The rest get through." | The other packets. | The packets outside the band, and 1 and 10, pulse one after another along the plot (0.12 s each). The band, bursts and caption fade out. | "the rest get through" | — |
| 12 | "There is a catch." | The arrows, the dashes, the `47 radio channels` brace and the damaged packets fade out. The now line slides back to the left edge, and each packet fades out as the line passes back over it, except packet 0. | Rewind on "a catch" (1.0 s, smooth). | none | New: the rewind. |
| 13 | "The drone's radio can only listen to one radio channel at a time, the green bar." | A green rectangle covering the plot's full height and width (fill 0.08) closes vertically to one lane on channel 57, around packet 0. The `RX` tag at its right end, with `drone's radio` under it. A small brace on the bar's height beside `RX`: `one radio channel`. | Rectangle appears on "The drone's radio"; closes on "one radio channel at a time" (1.0 s); the brace on "one radio channel"; the bar's fill pulses 0.2 → 0.45 → 0.2 on "the green bar". | "the drone hears one radio channel at a time" | Reuse the `win` closing animation, now plot-wide; brace new. |
| 14 | "After every packet it retunes, so it is already waiting when the next packet arrives." | Slots 1 to 4 at 0.6 s per slot, then the wait. | On "retunes" the bar jumps from channel 57 to 112 (0.3 s) and the now line then crosses slot 1 and packet 1 draws inside the bar; for slots 2 and 3 the bar jumps first, the packet lands second: 167, 222. For slot 4 the bar makes the long drop from 222 to 21 (0.4 s) and sits on the empty lane for 0.8 s while the now line is still in the gap; its fill pulses once on "already waiting". Then packet 4 draws into it on "arrives". | "already waiting when the packet arrives" | New: the jump. |
| 15 | "The transmitter makes the same move, so both ends are always on the same radio channel." | The `TX` tag and pointer at the bar's left end arrive here. Slots 5 to 12 at 0.6 s per slot. | `TX` appears on "The transmitter" and moves with the bar; at each jump the `TX`, bar and `RX` jump together: 76, 131, 186, 241, 40, 95, 150, 205. `TX` pulses on "same move". | "both ends on the same radio channel" | — |

End frame: the wide plot with packets 0 to 12 drawn (packet 6 is drawn normally in this pass), the bar on channel 4
(slot 13) waiting, the now line in the gap before slot 13, tags `TX` and `RX`, axes, no caption. Built by
`parts.hop_plot(13, 13)`.

The camera does not move from beat 4 to the end, the plot shows the whole band, and the bar's jumps are between 55 and 201
channel numbers each, which is 1.65 to 6.0 plot units of 7.4. The jump at slot 4 crosses most of the frame.

### S04b · the hop sequence and binding (`s04b_binding.py`, class `S04B`, about 46 s)

Layout for beats 1–5: the plot fades to `DIM` and stays behind. In front, two columns: `transmitter` (`BLUE_A` header) at
x = −4.6 and `drone` (`GREEN_A` header) at x = +4.6, each a box 2.4 × 4.4 centred at y = −0.2. Each box has an `ID` slot
at the top (a small rounded tag) and a list of seven rows below it. Between the boxes, at y = −0.2, one horizontal lane.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "For that, both need the same list of radio channels in the same order: the hop sequence." | The channel numbers of the first six packets lift out of the plot as `mono` numbers and line up as a vertical list in the middle: `57 112 167 222 21 76 …`. The plot dims. The list splits into two copies that move into the two boxes. A brace beside each list: `hop sequence`; under the transmitter's list in `MUTED`: `47 entries`. | Numbers lift on "the same list"; split on "both need"; a highlight steps down both lists together, row by row, on "in the same order"; braces on "the hop sequence". | "the hop sequence: 47 radio channels, in order" | New. |
| 2 | "The drone gets it once, in a step called binding." | The drone's list rows and its `ID` slot empty out, leaving dashed outlines. The transmitter's `ID` tag fills (`BLUE_A`, text `ID`). The dimmed plot fades out completely. | Emptying on "The drone gets it once"; caption on "binding". | "binding" | New. |
| 3 | "In bind mode it listens on radio channel 0, where the transmitter sends bind packets." | A tag `bind mode` under the drone's header. Between the boxes, the green bar (same object as in S04a, 4.6 wide, one lane high) with the label `radio channel 0` under it. It does not move. Small blocks (`packet_block(1.0, color=BLUE_A)`) travel left to right inside the bar. | Tag on "bind mode"; bar on "radio channel 0"; blocks, one every 0.6 s, linear, from "sends bind packets". | none | Reuse the bar and `packet_block` in `BLUE_A` (not yellow: these are not the packet we follow). |
| 4 | "They carry the transmitter's ID and the hop sequence, a few entries at a time, and the drone stores both." | One block stops mid-way and opens into a short cell row above the bar: one cell holding the `ID` tag, then five cells `0 57 112 167 222`. Braces: `ID`, `5 entries`. The cell row closes and the block arrives. The `ID` tag flies into the drone's ID slot; the five numbers fill its first rows. Two more blocks arrive and fill more rows, then `…`. The transmitter's list is redrawn to match (`0 57 112 167 222 21 …`). | Opens on "They carry"; ID cell pulses on "the transmitter's ID"; the five cells on "a few entries at a time"; first fill on "stores both"; the next two blocks 0.5 s apart. | "a bind packet: the ID and five entries" | New. Real layout: `11 03 01 id0 id1 idx hop[idx..idx+4]` (`packet.h` `d8_build_bind`); entry 0 of the table is channel 0, which is why the first packet's entries start with 0. |
| 5 | "The ESP32 binds the same way, with its own ID." | The left header `transmitter` becomes `ESP32`. Its `ID` tag changes colour from `BLUE_A` to `YELLOW_A`; one more block crosses and the drone's stored `ID` tag turns `YELLOW_A` too. | Header on "The ESP32"; tag colour on "its own ID". | none | New. No ID bytes are printed (the followed packet carries the E8's cloned ID). |
| 6 | "From then on the drone only listens to that ID, and it knows which radio channel comes next." | A block with a `RED_A` tag arrives at the drone box and stops at its edge with a small cross, then fades. A block with the `YELLOW_A` tag arrives and passes in, with a small `✓` (`GREEN_A`). `bind mode` tag and the bar fade. Then the boxes fade out and the hop plot of the S04a end frame comes back at full opacity, bar waiting on channel 4. | Red block on "only listens"; yellow block on "that ID". Cross-fade to the plot on "it knows" (0.8 s). Then slots 13 and 14: bar waiting, packet lands, bar jumps to 59 ahead of its packet, packet lands; each jump falls on "which radio channel comes next". | "other IDs are ignored" | New; reuse `hop_plot(13, 13)`. |
| 7 | "The timing it takes from the packets themselves." | The plot, slots 13 and 14 playing again, 0.9 s per slot. | As each of the two packets lands, a short tick drops from its left edge to the time axis, and the bar's next jump follows that tick. | "each packet times the next hop" | New: the ticks. Binding gives the list and the ID; the timing is kept during the link. |
| 8 | "To the drone, this is a steady stream of packets." | The axes, bar, tags and now line fade. The packets drop out of their heights into one row in time order. **View change 4**: camera to width 10 on the row; more packets fade in off both edges. | Existing collapse and camera move. | "a steady stream of packets" | Reuse; caption text changed from "continuous stream of packets". |
| 9 | "One of them is ours, carrying 1150." | **View change 5**: camera to `STREAM_W` on our packet (packet 0); the others dim. | Existing. | "our packet, carrying 1150" (`STREAM_CAP`) | Reuse. |

End frame: `packet_stream_close()` with `STREAM_CAP`. Same as today.

### S05 · into the drone (`s05_drone.py`, class `S05`, about 46 s)

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "The drone's radio chip, a CC2500, is built for FSK." | Our packet; the strip opens, marker `2.4 GHz` → `CC2500`. | Existing. | "the drone's radio chip: a CC2500" | Reuse; caption text changed. |
| 2 | "It catches the burst," | The block opens back into the wave. | Existing. | none | Reuse. |
| 3 | "reads the shifts back as ones and zeros," | The wave with the slot-centre dots of S03b on a small frequency trace above it; the dots become the bit squares. | Existing read-back, with the dots added: each dot appears, then its bit square. | "the wave, read back into bits" | Reuse; dots from S03b. |
| 4 | "reassembles the packet," | Bits regroup into the 20-byte row. | Existing. | "the bits, back in their packet" | Reuse. |
| 5 | "and checks the checksum." | Checksum cells pulse. | Existing. | none | Reuse. |
| 6 | "Everything checks out." | `✓` beside the row. | Existing. | "checksum ok" | Reuse. |
| 7 | "It hands the packet to the flight controller, the drone's main computer, over a link on the board called SPI." | Strip opens; marker `CC2500` → `SPI` and rests on the SPI segment. A small `MUTED` label under the `flight ctrl` box: `the drone's main computer`. | Marker on "hands the packet"; label on "main computer". | "over SPI to the flight controller" | Reuse; label new. |
| 8 | "Like UART, SPI sends bits over wires," | The byte `bd` lifts out of cell 6 and shows its bits `1 0 1 1 1 1 0 1`. They become a wire trace at y = −1.2, drawn exactly like the UART trace of S02a (same heights, colours, slot width 0.9, labels `high = 1`, `low = 0`), with tags `CC2500` at the left end and `flight ctrl` at the right. Label `data` at the left. | On "Like UART" a small `MUTED` note appears above the trace: `UART: one wire, agreed speed`. Byte lifts on "sends bits"; the trace draws left to right on "over wires", linear. | "SPI: bits on a wire again" | Reuse `parts.wire_trace`. No start or stop slot here. |
| 9 | "but an extra wire carries a clock that says when to read each bit." | A second trace under the first at y = −2.3: a square wave with one pulse per slot, `MUTED`, label `clock`. From each rising edge a thin dashed guide up to the data trace, ending in a dot on it (`ONE`/`ZERO`). | Clock trace draws on "an extra wire carries a clock". Then the guides and dots appear one by one, left to right, on "when to read each bit", and each dot's bit digit lights in the `1 0 1 1 1 1 0 1` row above. The UART note fades. | "the clock says when to read" | Reuse `wire_trace` for the clock. The clock comes from the flight controller's side (it is the SPI master); draw its label next to the `flight ctrl` tag. |
| 10 | "The flight controller runs firmware called Betaflight." | The traces fold back into `bd` in the row. Marker → `flight ctrl`, strip closes. The channel list appears with the header `flight controller`, and under it `running Betaflight` (`MUTED`). | Header on "The flight controller"; second line on "Betaflight". | none | Reuse the list; second header line new. |
| 11 | "It unpacks the throttle, 1150 again," | `0x6bd` lifts out of the throttle cells; `1725 ticks ÷ 1.5 =` appears briefly; `1150` lands in the list's throttle row. | Lift on "unpacks"; `÷ 1.5` on "throttle"; `1150` on "1150 again". | "the flight controller reads throttle 1150" | Reuse the lift; `÷ 1.5` is new and mirrors S02b beat 2. |
| 12 | "and mixes it into commands for the four motors, along with the corrections that keep the drone level." | Four motor commands. | Existing: the four commands on "four motors"; the level corrections on "keep the drone level". | "mixed into 4 motors" | Reuse. |
| 13 | "The motor drivers turn those into spin," | Props spin; marker → `motors`. | Existing. | none | Reuse. |
| 14 | "and the drone lifts." | The 3D quad lifts. | Existing. | none | Reuse. |

End frame: the lifted quad with spinning props, strip parked with the marker on `motors`.

### S06 · recap (`s06_recap.py`, class `S06`, about 17 s)

One slot under the opened strip, centred at y = −0.9, holds one object at a time. Each object arrives by a transform from
the one before it, so the recap is the whole video's chain of carry-overs in 17 seconds.

| # | Narration | On screen | Moves, and on which words | Caption | Reuse / new |
|---|---|---|---|---|---|
| 1 | "To recap: a key press becomes a number in the browser," | The quad of the S05 end frame shrinks and fades. The strip opens (`focus = 1`) and the marker travels back from `motors` to `keyboard`. In the slot: a `W` key cap (S01 style), which becomes `1150 µs`. | Strip opens on "To recap" (1.2 s, smooth); key cap lights on "a key press"; transform to `hero_number(48)` on "a number"; marker `keyboard` → `browser`. | none | Reuse `strip.open`, `strip.go`, key cap, `hero_number`. |
| 2 | "then bytes in a D8 packet," | `1150` becomes the 20-byte row (`packet_row(scale=0.55)`, no braces, throttle cells lit). | Transform on "bytes"; marker `browser` → `ESP32` along the cable. | none | Reuse `packet_row`, `light_throttle`. |
| 3 | "then frequency shifts," | The row becomes the coloured wave of the eight hero bits, with its step trace above it (two rungs). | Transform on "frequency shifts". | none | Reuse `fsk_wave`, `freq_trace`. |
| 4 | "sent by a Wi-Fi radio switching between two test tones." | Labels `+39 kHz` / `−39 kHz` on the two rungs; a small `two test tones` tag beside them. | Tag on "two test tones"; marker `ESP32` → `2.4 GHz`, and the strip's air wiggle flows while it crosses. | none | Reuse. |
| 5 | "The drone's receiver reads the packet and acts on it." | The wave becomes the packet row again, then `1150`, then the top-view quad with turning props. Hold 1.5 s. | Row on "reads the packet" (marker → `CC2500` → `flight ctrl`); `1150` then the quad on "acts on it" (marker → `motors`). During the end hold the caption fades in under the quad. | `github.com/mb6611/esp32-d8tx` in `mono` | Reuse `quad_top`. |

End frame: opened strip with the marker on `motors`, the small quad with turning props under it, the GitHub address under it.

## 3. Seams and view changes

Carry-over frames (last frame of scene n is the first frame of scene n + 1, built from the same helper):

| Seam | Frame | Helper |
|---|---|---|
| S00 → S01 | strip parked, marker on `keyboard`, nothing else | `MapStrip(K_KEY)` |
| S01 → S02a | `1150 µs` centred, marker on `browser` | `hero_number()` (as today) |
| S02a → S02b | `1150 µs` centred, marker on `ESP32` | `hero_number()` |
| S02b → S03a | the 160 bits at `UZOOM_W`, throttle bits lit | `bit_cells()` (as today) |
| S03a → S03b | bits, three rows, slot guides, wave at rest | new `parts.fsk_rows(...)`, or the same construction code in a shared function |
| S03b → S03c | bits, enlarged step trace ±32 kHz with sample dots, strip `DIM` | `freq_trace(smooth=0)` + dots |
| S03c → S04a | the packet block centred | `packet_block_big()` (as today) |
| S04a → S04b | wide hop plot, 13 packets, bar waiting on slot 13 | `hop_plot(13, 13)` |
| S04b → S05 | our packet in the stream, caption | `packet_stream_close()`, `STREAM_CAP` (as today) |
| S05 → S06 | lifted quad, marker on `motors` | the S05 quad builder, moved to a function |

Camera moves and whole-frame rearrangements in the video (the camera moves in 1, 3, 4, 5 and 6 only):

1. S02b beat 15: move in on the throttle's bits (exists today).
2. S03c beat 18: eight bits → the whole packet as a bar (a redraw, the camera does not move).
3. S04a beat 4: pull back from one lane to the whole band.
4. S04b beat 8: to the stream row (exists today).
5. S04b beat 9: in on our packet (exists today).
6. S05: the existing move to the 3D quad, unchanged.
7. S03b beats 9 and 16: row 1 and the two panels rearrange (objects move, the camera does not).
8. S03c beat 15: the four-row side-by-side layout (objects move, the camera does not).

No other beat moves or zooms the camera. In particular nothing follows the hops in S04a.

## 4. Sentences with a weak picture

Each has a picture in the table; the alternative is given in case the owner or a scene author prefers it.

- **V1. "Fourier analysis explains why; we won't go into it."** (S03b beat 13) In the table: a label `Fourier analysis` on an
  arrow from the time panel to the frequency panel, then dimmed; the frame is otherwise still. Alternative: no new
  object, and the `sharp` sweep of the previous beat continues once more under the sentence.
- **V2. "Hopping protects the link."** (S04a beat 8) In the table: a highlight runs along the hop arrows. Alternative: a
  still frame for these four words.
- **V3. "This one is only partly that, as we'll see."** (S00 beat 14) In the table: the morphing wave settles into the
  plain two-frequency wave and `pseudo` pulses. Alternative: a small `?` beside `pseudo` that stays until S03c beat 14
  answers it; clearer pay-off, one more mark to carry in memory.
- **V5. "And D8 doesn't need an arbitrary signal."** (S03c beat 8) In the table: still frame. Alternative: the dashed ghost of
  the arbitrary wave returns and is struck through here instead of in beat 3.
- **V6. "so packets sent there can interfere with it if both are sent at the same time."** (S04a beat 10) A packet and a
  Wi-Fi burst colliding is drawn as two red-and-yellow overlapping rectangles; the Wi-Fi bursts are an invented
  illustration of traffic (no capture backs them), and the caption must not suggest a measured loss rate.

Labels that now contradict the older narration and are changed in the tables: `header` → `length`, `counter` →
`bookkeeping`, `8 stick values` → `8 control channels`, "stick" → "channel" in three S02b captions, `channel A` /
`2.404 GHz` removed from S03a, `+39 kHz` on row 1 deferred to S03c. The S01 bars read `THR AIL ELE RUD`; the narration
says throttle, yaw, pitch, roll. Suggest relabelling the bars `throttle roll pitch yaw aux1 aux2 arm aux4` (the packet's
order), or accept the mismatch.

Technical claims checked: 8.994 ms per packet (111 a second); 1150 × 1.5 = 1725 = 0x6BD; 20 bytes = 160 bits, with 6 more
bytes (4 × AA, D3 91) in front, 208 bits × 32.2 µs = 6.70 ms; bytes 3–5 are `00`, counter, `01`; 31,044 baud; 39.06 kHz per
tone step (1 in 61,500 of 2.4 GHz); 299.93 kHz channel spacing; 47 hop entries from channel 0 to 245; 12 of them inside
Wi-Fi channel 6; bind packets on channel 0 with the ID and five entries each; CC2500 on SPI; the USB bridge is a CP2102.

## 5. Decided

All earlier open questions are answered: eleven scene files; true frequency axis for the hop plot; the demo address
`d8tx.mb6611.workers.dev` on screen in S01 and the GitHub address at the end of S06; 9 to 10 minutes; the E8's
cloned identity in the followed packet; the intro drawn, no footage; the Wi-Fi interference line as written in the script.
