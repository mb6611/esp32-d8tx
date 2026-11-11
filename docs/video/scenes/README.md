# Scene authors: shared pieces for the 11-scene long cut

Files and classes (order = `stitch.sh`): `s00_intro.py S00`, `s01_key_to_stick.py S01`, `s02a_to_esp32.py S02A`,
`s02b_packet.py S02B`, `s03a_fsk.py S03A`, `s03b_gfsk.py S03B`, `s03c_tones.py S03C`, `s04a_hopping.py S04A`,
`s04b_binding.py S04B`, `s05_drone.py S05`, `s06_recap.py S06`. Narration is SCRIPT-draft.md, pictures STORYBOARD*.md.
Work only in your own scene file. Need a shared helper changed? Ask the orchestrator; do not edit `parts.py`/`common.py` yourself.

Most files are **skeletons**: `construct()` calls `skeleton(...)`, which enters the incoming seam, speaks one line, cuts to the
outgoing seam. Replace it with the real scene, but start from the incoming seam and end on the outgoing one (below).
`s02b_packet.py`, `s03c_tones.py`, `s04a_hopping.py` also contain the old scene (`S02_old`, `S03_old`, `S04_old`, not rendered)
and its module-level helpers, as a source to copy from; delete it when you are done. `s01` and `s05` are the old scenes, unchanged
except that `s05` builds its quad with `parts.quad3d()`.

## Rendering (read this)
- Always `./render.sh <manim args>`, never bare `manim`. It gives every scene file its own media dir `media/<file>/`
  (Tex, texts, voiceovers, videos), so renders of **different scenes run in parallel** with no limit; a lock per dir only stops
  two renders of the *same* scene. First render of a scene is slower (its Tex/voiceover caches start empty).
- Iterate: `./render.sh -ql -o S03B scenes/s03b_gfsk.py S03B` -> `media/s03b_gfsk/videos/s03b_gfsk/480p15/S03B.mp4`.
- Final: `./render.sh -qh --disable_caching -o S03B scenes/s03b_gfsk.py S03B` (1080p60 -> `.../1080p60/S03B.mp4`).
- `./stitch.sh [480p15|1080p60]` joins the 11 videos from their media dirs (`ALLOW_SILENT=1` tolerates scenes without audio).
- Seam check: `frames/v10/seams/seams.sh` extracts the first/last frame of each scene and prints the PSNR of last(n) vs first(n+1)
  (about 43 or more = same picture; a seam break shows as below 30).

## Rules
- The camera never moves except for a storyboarded view change (S02b end, S04a beat 5, S04b stream, S05 3D). No push-ins or
  drift under speech. Motion goes on objects and is tied to the words. Captions `FadeIn`/`FadeOut`, never written on.
- Colours, stroke widths, fonts only from `common.py`: `YELLOW_A` the piece we follow, `ONE`/`ZERO` bit values, `GREEN_A`
  receiver, `BLUE_A` transmitter/host, `MUTED` labels, `STRUCT` outlines, `GRID` guides, `DIM` = 0.3 opacity; strokes `SW_THIN`,
  `SW`, `SW_LINE`, `SW_FLASH`. Text through `label()` (roman), `num()`, `mono()` (bytes/bits), `caption_at(frame, text)`.
- Time-like motion (cursor sweeps, the now line) is `linear`; spatial moves `smooth`.
- Never git commit/stash/reset.

## Narration
`class S0x(Narrated, MovingCameraScene)` (`ThreeDScene` for S05/S06), then
`with self.voiceover(text="Written form, 6BD and 1150 µs.") as tr: self.play(..., run_time=tr.duration)`.
`Narrated.voiceover` respells the text for the voice with `common.spoken()` (numbers, acronyms, units: 2-FSK, UART, 32 kHz, 1150 ->
"eleven fifty", 15 % ...); write the **written** form in the call, the on-screen text keeps it. Voice: macOS `say` Samantha via
`voice_service()` (offline). Extend `common._SPOKEN` (ask the orchestrator) if a word sounds wrong. Use `<bookmark mark='x'/>` in the
text and `self.wait_until_bookmark('x')` to sync a picture to a word.

## Seams: `Seam` objects from `parts.py`
`seam = seam_x_y(); strip = seam.enter(self)` adds the whole frame (camera set, `MapStrip`, mobjects, caption) and returns the
strip. A Seam has `.mobs` (VGroup), `.cam` (centre, width), `.strip_kw`, `.caption_text`. Both scenes call the same function.
| Seam | Function | Frame |
|---|---|---|
| S00 -> S01 | `seam_s00_s01()` | strip parked, marker on `keyboard`, nothing else |
| S01 -> S02A | `seam_s01_s02a()` | `hero_number()` centred, marker `browser` |
| S02A -> S02B | `seam_s02a_s02b()` | `hero_number()`, marker `ESP32` |
| S02B -> S03A | `seam_s02b_s03a("out")` / `("in")` | the 160 `bit_cells`, throttle lit: S02B ends at camera width `UZOOM_W` (bits at k=1), S03A starts at full frame (k=`K3`); identical picture |
| S03A -> S03B | `seam_s03a_s03b()` | `fsk_rows()`: bits y=2.4, row 1 step trace + `a little higher/lower/centre`, row 2 carrier, row 3 wave at rest, `+ =`, `wave exaggerated`, guides, axis titles; strip not dimmed |
| S03B -> S03C | `seam_s03b_s03c()` | `row1_big()`: bits y=2.4, row 1 at y=0.6 (levels +-0.85) step trace `+32 kHz/-32 kHz`, sample dots + lines, guides; **strip DIM** |
| S03C -> S04A | `seam_s03c_s04a("out")` / `("in")` | packet block: `packet_block_big()` centred (full frame) / `packet_block()` at `HP_P0` with camera (`HP_P0`, `CLOSE_W`) |
| S04A -> S04B | `seam_s04a_s04b()` | `hop_plot(13, 13)` through camera `HP_CAM` (centre (6.2, 3.7), width 18); marker on `2.4 GHz` |
| S04B -> S05 | `seam_s04b_s05("out")` / `("in")` | our packet in the stream + `STREAM_CAP`: camera `STREAM_W` on it / full frame (`packet_stream_close()`, as S05 builds it) |
| S05 -> S06 | `seam_s05_s06()` | lifted 3D quad (`quad3d_lifted()`) at `QUAD_PHI/QUAD_THETA`, marker on `motors`; `.quad`, `.props` |
Strip state per scene: `strip_kw` = `dict(pos=K_*, dim=bool, focus=0..1)`; the strip is parked (focus 0) at every seam. `MapStrip`
also has `.dim()` / `.undim()` animations (S03b dims, S03c undims) next to `.go(pos)`, `.open()`, `.close()`.
S05->S06 end state (theta, prop angle) was measured from the old S05's last frame; if you change S05's ending, keep that frame or
tell the orchestrator. S04a's "close view" block is at `HP_P0` (packet 0 in hop-plot coordinates).

## Helpers in `parts.py` (new ones)
- `quad_top(scale, center)` 2D top-view quad; `quad3d()` -> `(VGroup, props)`; `quad3d_lifted()`.
- `bit_cells(k, center, lit)` (old), `hero_bit_squares(y)` the 8 throttle bits at their slot x (`bit_x(i)`).
- `freq_trace(bits, smooth, dev, center, width, hi_text, lo_text, mid_text, dots, link_y)` -> `FreqTrace` (`.zero .segs .risers
  .dots .links .hi .lo .mid`). `smooth=0` step trace, `smooth>0` Gaussian glide (1 = sigma 0.14 bit); same pieces, so `Transform` works.
- `slot_guides(y_top, y_bot)`; `fsk_rows(cursor)` -> `FskRows` (parts as attributes); `row1_big(smooth)`.
- `carrier_wave`, `pieces_ph`, `wave_ph`, `carrier_ph` (moved from the old S03), constants `Y1 LV Y2 A2 Y3 A3 XL XR OPX CYC_A K3 BX`.
- `wire_trace(bits, pitch, center, idle, tag_l, tag_r)` -> `WireTrace` (`.segs .risers .digits .guides .hi_lab .lo_lab .tag_l .tag_r .x(i)`);
  `idle=True` for UART (S02a), `idle=False` for SPI (S05). `clock_trace(n, pitch, center)` SPI clock.
- `spectrum_panel(sharp, center, w, h)` and `spectrum_curve(sharp, center, w, h, color, wide)`: ILLUSTRATIVE curves (flag T4); use
  `always_redraw(lambda: spectrum_curve(sharp.get_value(), ...))` for the `sharp` sweep.
- `margin_block(words, y)`, `margin_arrow(y)`.
- `hop_plot(n_packets, bar_slot, now, bar)` -> `HopPlot`: true frequency axis (channel n = y n*0.03, 0..246, 2.404..2.478 GHz),
  18 slots of 0.7, packets 0.525 x 0.2, green bar 0.25 high. Attributes `.pkts` (all 18), `.arrows` (17), `.bar .rx .tx .now`, `.axes`,
  and built-but-not-added `.dashes` (47 channels), `.brace47`, `.wifi` (channels 77-143). `HP_CH` = channel per slot, `hp_x(slot)`, `hp_y(ch)`,
  `HP_CAM`, `HP_K` (scale labels by it in the width-18 view).
- `packet_block_big()`, `packet_stream_close()`, `STREAM_CAP`, `STREAM_W`, `CLOSE_W`, `hero_number()` (old, shared).
