# Style guide: what to borrow from 3Blue1Brown for the d8tx explainer

Companion to `STORYBOARD.md` (content) and `common.py` (colours, fonts). This file is about
*how things move*. Manim Community 0.22 names are given for every technique; 3b1b's own code
(manimgl) is cited so you can read the original.

Sources read: `3b1b/videos` `_2018/fourier.py` (FourierMachineScene, WrapCosineGraphAroundCircle,
DrawFrequencyPlot), `_2024/transformers/{attention,embedding,helpers}.py` (AttentionPatterns,
IntroduceEmbeddingMatrix, ThreeDSpaceExample), `_2022/convolutions/discrete.py` (SimpleExample),
`_2017/nn/part1.py` (NetworkMobject, NetworkScene.feed_forward); the Fourier lesson text at
3blue1brown.com/lessons/fourier-transforms; Lex Fridman #64 (on layers of abstraction).
YouTube frame extraction was not available in this environment, so timestamps are approximate
and the code is the primary evidence.

## 0. Organising principle (owner's direction)

The viewer follows ONE concrete piece the whole way: throttle `1150 µs` → raw `0x6bd`
(`d8_us_to_raw`: (1150·3+1)/2 = 1725) → its low byte `0xbd` at body offset 8 (air byte 14,
`packet.c` `lo[2]=8`) → its bits `1 0 1 1 1 1 0 1` (MSB first) → eight tone segments → one
packet in one hop slot → one motor command. Never summarise a stage with a static diagram when
the piece can be seen moving through it. The camera stays on the piece; it pulls back only to
reveal structure, then returns.

This is exactly the 3b1b pattern. In *Attention in transformers* one token ("creature" in
"a fluffy blue creature roamed the verdant forest") is followed from word → embedding → query
vector → dot products → weighted sum, and everything else is faded to 0.25–0.5 opacity while it
moves (`attention.py` AttentionPatterns, `a_bubbles.animate.fade(0.5)`,
`ndp_columns[:index].animate.set_opacity(0.35)`). In the convolution video `(1,2,3)*(4,5,6)` is
followed term by term (`discrete.py` SimpleExample "March!" loop). In the Fourier video a single
3 beats/s cosine is wound, weighed and plotted before any general signal appears.
Grant on Lex Fridman #64: be explicit about layers of abstraction and resist starting from the
top; show the specific thing first, let the general shape arrive as a summary.

## 0b. Numbers on screen (owner's direction)

Balance: not a wall of exact figures that hides the idea, not so general that nothing is
concrete. Per stage the frame carries:
- **The piece's own number**, exact: `1150 µs` → `0x6bd` → `bd` → `1 0 1 1 1 1 0 1`.
- **At most one or two anchor numbers** that give scale, in round form in captions:
  `8 channels`; `20 bytes`; `±39 kHz`; `47 channels, about 9 ms per hop`; `4 motors`.
- **Everything else stays out of the frame** or appears briefly at 0.25 opacity: the CRC
  polynomial, baud to the unit, step formulas, register names, the hex of every other byte,
  the hop-table arithmetic. Keep those in code comments (with the source file) so the picture
  is still exact; the caption is not where they live.
- Exact values only where the piece itself shows them (the counter stopping at `1150`, the
  two destination cells `bd` / `6`); `about 9 ms`, `about 39 kHz` elsewhere.
- Each caption: one idea, under ~10 words.

This matches 3b1b: in *Attention* the single anchor `12288` is counted in with a brace once,
the matrices are shown as generic grids of random decimals at low opacity, and the one token
being followed is the only thing with legible values.

## 1. Techniques

Each: what, why, where he does it, how in Manim CE 0.22.

### 1.1 Continuity: one object persists and transforms
- **What.** The thing you were looking at *becomes* the next representation; nothing is cut and
  replaced. The number becomes the hex pair; the hex pair becomes eight squares; the squares
  feed a trace.
- **Why.** Identity survives the change of representation, so the viewer never re-finds the piece.
- **Where.** `discrete.py` SimpleExample: `TransformMatchingShapes(conv[1:6:2].copy(), top_row)`
  turns the typed `(1, 2, 3)` into three value blocks; then `TransformFromCopy(label_pair,
  new_label_pair)` lifts the aligned pair into the product expression; then
  `FadeTransform(expr.copy(), rhs[...])` collapses the expression into the result digit.
  `fourier.py` wrap_around_circle: `ReplacementTransform(moving_graph, polarized_graph,
  run_time=3, path_arc=-TAU/2)` — the time graph *bends* into the wound graph along an arc.
- **CE 0.22.** `ReplacementTransform(a, b)`; `TransformMatchingShapes(a, b)` for text/hex;
  `TransformFromCopy(a, b)` when the source must stay (the byte stays in the row while a copy
  unrolls into bits); `FadeTransform(a, b)` for a soft collapse; `path_arc=` on any Transform to
  make the move legible; `MoveAlongPath(dot, path)` for a piece travelling down a wire.
  Keep a reference to the moving mobject across the whole scene; do not rebuild it.

### 1.2 Camera as narrator
- **What.** The frame moves with the piece: nudge to keep it centred, pull back to reveal the
  structure it lives in, return.
- **Why.** The viewer's attention is *steered*, not asked. Pull-backs are the "aha" delivery.
- **Where.** `attention.py` AttentionPatterns: `frame.animate.move_to(LEFT)` with each new
  column; `frame.animate.set_height(11).move_to(all_rects, UP)` when the whole matrix product
  appears; `frame.animate.set_height(15, ...).set_anim_args(run_time=3)` for the big reveal —
  reveals are slow (3 s), nudges are default (1 s). `embedding.py` IntroduceEmbeddingMatrix:
  `frame.animate.set_width(FRAME_WIDTH + 3, about_edge=RIGHT)` widens *about an edge* so the
  thing being discussed does not drift. `ThreeDSpaceExample`: `frame.reorient(-15, 78, 0,
  center, height)` then `add_ambient_rotation(1 * DEGREES)` (slow drift while nothing happens).
- **CE 0.22.** 2D: `MovingCameraScene`, `self.camera.frame.animate.scale(k).move_to(m)` or
  `.set(width=...)`; `self.camera.frame.save_state()` / `Restore(self.camera.frame)` for the
  return. 3D: `ThreeDScene`, `self.set_camera_orientation(phi=, theta=, zoom=, frame_center=)`
  at start; `self.move_camera(phi=, theta=, zoom=, frame_center=, run_time=3)` for moves;
  `self.begin_ambient_camera_rotation(rate=0.02)` / `stop_ambient_camera_rotation()` for the
  idle drift; `self.add_fixed_in_frame_mobjects(caption)` for HUD text. Count camera moves per
  scene: 3b1b averages ~1 camera move per 3 `play` calls; most are small.

### 1.3 Introducing an abstraction: instance first, then shape
- **What.** Show the one concrete case fully, *then* the general container (the other columns,
  the other channels, the other 207 bits).
- **Where.** `embedding.py` IntroduceEmbeddingMatrix: 20 real words → a single column lit at a
  time (`group.target.set_opacity(0.2); group.target[index].set_opacity(1)`) → only then the
  label `W_E`. Fourier video: one cosine (3 bps) is wound at one winding frequency, then the
  winding frequency is varied, then a second signal, then the sum.
- **CE 0.22.** Build the full structure up front but `set_opacity(0)` or `set_opacity(0.2)` on
  everything except the instance; reveal the rest with `LaggedStartMap(FadeIn, rest,
  lag_ratio=0.05)`. Add the name (`Text`) *last*, next to the structure.

### 1.4 Reveal pacing and pauses
- **What.** Build → beat → build. One idea per `play`, then `wait()`.
- **Numbers from the code (attention.py, 216 plays / 148 waits).** `self.wait()` with no
  argument (1 s) is 139 of 148 waits; a few `wait(2)`, `wait(5)` for a complex frame to settle.
  `run_time`: 2 s is by far the most common (41), then 3 (13), 4–6 for big transforms/reveals,
  1–1.5 for small moves, 0.5 for flashes. So the rhythm is: 2 s move, 1 s hold.
- **Why.** Without narration (our case) the hold *is* the reading time. Give at least 1 s hold
  after every caption and 2 s after any frame with more than ~3 new objects.
- **CE 0.22.** `self.play(..., run_time=2)`; `self.wait(1)`; `rate_func=smooth` (default) for
  moves, `linear` for anything representing time passing (bit clock, hop clock, props),
  `there_and_back` for a nudge that returns. CE has no `time_span=`; stagger inside one play
  with `AnimationGroup(a, b, lag_ratio=0.3)` or `Succession(Wait(0.5), b)`.

### 1.5 Dim-and-highlight
- **What.** Everything that is not the piece drops to 0.2–0.35 opacity; the piece stays at 1
  and gets a thin `SurroundingRectangle`.
- **Where.** `embedding.py` column walk: `set_opacity(0.2)` on all, `1` on index, `FadeIn(rect)`
  with `FadeOut(last_rect)` in the same play so the box *jumps*. `attention.py`: `set_opacity(0.35)`
  on past/future columns; `paragraphs.animate.set_opacity(0.25)`. Rect style there:
  `set_stroke(WHITE, 1)`, `buff=0.05`; or `.set_stroke(YELLOW, 1).round_corners()`.
- **CE 0.22.** `group.animate.set_opacity(0.25)`; `SurroundingRectangle(m, buff=0.08,
  stroke_width=1.5, color=YELLOW_A, corner_radius=0.08)`; brief attention: `Indicate(m,
  scale_factor=1.1)`, `Circumscribe(m, run_time=0.8)`, `Flash(m)`. Prefer dimming over adding
  arrows.

### 1.6 Lagged / staggered animations
- **What.** Many similar things appear or move one after another, overlapping.
- **Numbers.** `lag_ratio` in attention.py: 0.1 (33 uses), 0.25 (17), 0.01 (14), 0.05 (13),
  0.2 (10), 0.5 (8). Rule of thumb: 0.01–0.05 for writing many glyphs, 0.1–0.25 for rows of
  objects, 0.5 when each item should be seen individually (bits!). 173 uses of `LaggedStart*`
  across the two transformer files — it is the default for anything plural.
- **Where.** `embedding.py`: `LaggedStartMap(FadeIn, shown_words, shift=0.5*LEFT, lag_ratio=0.1,
  run_time=2)`; `nn/part1.py` `get_edge_propogation_animations`:
  `ShowCreationThenDestruction(edge_copy, lag_ratio=0.5)` — a pulse travelling along wires.
- **CE 0.22.** `LaggedStart(*anims, lag_ratio=0.1)`, `LaggedStartMap(FadeIn, group, shift=0.3*LEFT,
  lag_ratio=0.1)`; pulse along a wire: `ShowPassingFlash(path.copy().set_stroke(width=6),
  time_width=0.3)`; eight bits one at a time: `LaggedStart(..., lag_ratio=0.5, run_time=4)`.

### 1.7 Labels
- **What.** One to four words, placed next to the object (`next_to(obj, DOWN, SMALL_BUFF)`),
  appearing *with* or just after the thing they name, often coloured like it. Dimension counts
  are `Integer` objects counted in (`CountInFrom(dim_value, 0)`), with a `Brace`.
- **Where.** `attention.py`: `Brace(q_vect, LEFT, SMALL_BUFF)` + `Text("Query").set_color(YELLOW)`
  + later a second line `"128-dimensional"` slid in under it (`FadeIn(dim_text, 0.1*DOWN)`).
  Labels fade in with a tiny shift (`FadeIn(x, 0.25*LEFT)`), never `Write` for short labels.
- **CE 0.22.** `Brace(m, LEFT)` + `brace.get_text(...)`; `FadeIn(label, shift=0.2*DOWN)`;
  numbers: `Integer`/`DecimalNumber` with `ChangeDecimalToValue(num, 1150, run_time=2)` or a
  `ValueTracker` + `always_redraw`. Caption word budget for us (no narration): title ≤ 5 words,
  caption ≤ 8 words, label ≤ 3 words; never two captions on screen at once; a caption appears
  with the object it describes and leaves when the object leaves.

### 1.8 Colour discipline
- **What.** One colour per *role*, kept for the whole video; the moving piece keeps its colour
  across representations (the yellow in `(1,2,3)*(4,5,6)` result stays yellow through
  `c_n` labels and the final tuple). Highlights are `YELLOW`; the follow-object is often white
  with a `GlowDot`. Backgrounds near-black; grids `GREY_B` stroke 1–2, `plane.fade(0.5)`.
- **For us (`common.py`).** `YELLOW_A` = the piece (1150 → 0xbd → its bits → its tone segments →
  its packet → its motor delta). `ONE`/`ZERO` only for bit values. `RED_A` RF, `GREEN_A` ESP32,
  `BLUE_A` host/app, `PURPLE_A` drone. Nothing else gets a new colour. Dimmed = same colour at
  0.25 opacity, not grey.

### 1.9 3D: when and when not
- **He goes 3D** when the third axis carries data and a 2D projection would hide it
  (`ThreeDSpaceExample`: vector coordinates built one axis at a time, each line coloured, the
  tip `GlowDot` moving; then "many points" and a 2D slice taken through the cloud). He adds
  `add_ambient_rotation(1–5 DEGREES)` so a still 3D frame never looks frozen, and pins all
  numbers to the frame (`fix_in_frame()`).
- **He stays 2D** for anything that is a sequence, a table, a graph or an equation, even if a
  3D version is possible (the embedding matrix, attention pattern, winding diagram are all 2D).
  The Fourier "winding" is 2D polar, not a helix.
- **For us.** S03 phasor: 3D is justified only if the *time* axis is the third axis (a helix
  whose pitch flips with each bit). If you draw the phasor as a circle plus a separate
  frequency trace, stay 2D — it is clearer and matches 3b1b. S04 hop grid: 2D plane with the
  camera tilting (`ThreeDScene` for the tilt only) is enough. S05 quad: 3D primitives, fixed
  orientation, slight ambient rotation.
- **CE 0.22.** `ThreeDScene`; `ThreeDAxes`; `ParametricFunction` for a helix;
  `add_fixed_in_frame_mobjects`; `begin_ambient_camera_rotation(rate=0.02)`;
  `Surface`/`Cube`/`Cylinder` for props and arms; `set_shade_in_3d(True)` on strokes that
  must occlude correctly.

### 1.10 Signals and frequencies (the Fourier machinery)
- **What he does** (`fourier.py` WrapCosineGraphAroundCircle, DrawFrequencyPlot; video ≈ 4:30–9:00):
  1. Time graph on top (`FunctionGraph` of 0.5·cos(2π f t), `num_steps=200`), a finite window.
  2. `get_polarized_mobject`: copy the graph and `apply_function(polarize_point)` — each point
     (t, g(t)) is mapped to radius g(t) at angle 2π·f_wind·t. The wound graph is *the same
     mobject* bent round the circle.
  3. A rotating `Vector` whose length tracks the signal height draws the wound graph
     (`get_vector_animations`), with a `Dot` sweeping the time graph in sync.
  4. A red centre-of-mass dot (`center_of_mass_dot`) tracks the winding; its x-coordinate is
     plotted against winding frequency as a `ValueTracker` sweeps (`animate_frequency_change`),
     tracing the "almost Fourier transform". The spike appears where f_wind = f_signal.
  5. Vertical lines mark periods (`get_v_lines_indicating_periods`) and are updated as the
     frequency changes, to show *why* the wound graph balances or not.
- **Why it works.** Every quantity is a visible thing (length, angle, balance point), the
  transform is done *to the graph you were looking at*, and the parameter is swept continuously
  so the spike is discovered rather than announced.
- **Map to 2-FSK.** Our signal has constant amplitude and a frequency that flips: +39.06 kHz
  for a 1, −39.06 kHz for a 0 (relative to the channel centre). So the "wound graph" is just a
  phasor of fixed length whose *direction of rotation* flips per bit: counter-clockwise for 1,
  clockwise for 0, each bit lasting 1/31044 s ≈ 32.2 µs (slow this down: ~1 s per bit on
  screen, with a time-stretch label). Under it, a frequency-vs-time trace draws itself at
  ±39 kHz (a two-level step function, `linear` rate), in `ONE`/`ZERO` colours. Then the
  spectrum: sweep a winding frequency (as he does) over the 8-bit segment and plot the
  balance → two spikes at ±39 kHz, i.e. the two tones the CC2500 listens for. That spike-pair
  is the "aha" of S03.
- **CE 0.22.** `ValueTracker` for time and for winding frequency; phasor
  `always_redraw(lambda: Arrow(ORIGIN, plane.polar_to_point(1, angle(t)), buff=0))`;
  `TracedPath(arrow.get_end, stroke_color=..., dissipating_time=2)` for the swept arc;
  `Axes.plot(step_fn, use_smoothing=False)` for the frequency trace; CE's
  `ComplexPlane` for the I/Q circle; for the spectrum, precompute with numpy and reveal with
  `Create(spectrum_graph)` while the frequency dot sweeps along the x-axis.

### 1.11 Discrete sequences becoming continuous signals (and back)
- **Where.** `discrete.py`: the two rows of integer blocks slide past each other
  (`get_row_shift`) and each aligned pair is boxed, lifted, multiplied; the output tuple fills
  one digit per step. Later in that video the same picture becomes the moving-average and then
  the continuous convolution: the blocks become bars become a curve. Fourier: the dots sampled
  along the graph (`graph.dots`, `ReplacementTransform(pre_dots, time_graph.dots, lag_ratio=0.5)`)
  are lifted to the wound curve so you see the sampled points become a continuous shape.
- **For us.** bits (eight squares) → each square *stretches* into a 32 µs segment on the time
  axis (`square.animate.stretch_to_fit_width(seg_w).move_to(axes.c2p(t_mid, 0))`) → the
  segment acquires its tone (the frequency step draws across it) → the phasor spins for that
  segment. The reverse at the receiver (S05): the trace is chopped back into eight squares and
  re-forms `0xbd`.
- **CE 0.22.** `Square.get_grid` equivalents: `VGroup(*[Square(0.5) for _ in range(8)])
  .arrange(RIGHT, buff=0)`; `Transform(squares[i], segment_i)`; `Create(step_graph,
  rate_func=linear)` synchronised with the phasor via one `ValueTracker`.

### 1.12 Typical scene lengths and on-screen text
- His `construct()` is cut into comment-headed blocks ("# Show embedding matrix", "# Label as
  W_E"); each block is 2–5 plays and ~8–20 s, and one *idea*. A scene is 4–8 blocks.
- Text on screen at once: usually one title-size object (font_size 36–90 in an 8-unit frame)
  plus labels; equations are the exception, and we have none. Numbers are `Integer`/
  `DecimalNumber`, not typed text, so they can count.
- For our 75 s, five scenes of 12–18 s = 3–4 blocks each. Each block: one move of the piece,
  one caption, one hold.

## 2. Shot list for the seven stages

The piece is drawn once in S01 as a yellow `DecimalNumber` `1150` with a small `µs` label; its
colour `YELLOW_A` is carried through every representation. Between scenes the last frame of
one and the first frame of the next show the piece in the same place and size (stitch cuts on a
still, see `stitch.sh`).

### Stage 1 — key (S01, ~4 s)
- W key cap, centred. `Indicate(key)`, key cap `shift(0.05*DOWN)` with `there_and_back`.
- Camera already framed so the stick gimbal is just off-screen right; a thin wire leaves the
  key to the right. Pulse along the wire: `ShowPassingFlash`.
- Caption: `W held` (then leaves). No numbers in this stage.

### Stage 2 — stick value (S01, ~6 s)
- Camera nudges right (`camera.frame.animate.move_to`) to the gimbal. The throttle stick rises
  while `DecimalNumber` counts `1000 → 1150` (`ChangeDecimalToValue`, run_time 2, `linear`),
  stops at the cap. Caption: `throttle: 1150 µs`. (The 15 % cap is a code comment, not a
  caption.)
- Pull-back 1 (small): reveal the 8-channel bar row; the throttle bar is lit, the other seven
  at 0.25 opacity and *without* their values. Caption: `one of 8 channels`. Hold 1 s.
  Anchor numbers this stage: `1150 µs`, `8 channels`. End on the number `1150` enlarged and
  centred — this is the carry-over frame.

### Stage 3 — bytes (S02, ~12 s)
- `1150` → `TransformMatchingShapes` straight into `0x6bd` (one move, path_arc; skip the
  `×1.5 = 1725` intermediate on screen — it is a code comment). Caption: `as a 12-bit value`.
  Hold.
- `0x6bd` splits: `TransformFromCopy` sends `bd` to body offset 8 and `6` to the low nibble of
  offset 11, in an 18-byte row that is already there at 0.25 opacity with its hex *illegible by
  design* (small, dim; bytes from the NOTE.md vector, cited in a comment). The two destination
  cells light and are the only readable hex; everything else dim. Caption: `packed into the
  packet`.
- Pull-back 2 (small): whole row for 1 s, still dim except our cells; a pulse runs left→right
  along the row (`ShowPassingFlash`) and two check bytes grow at the end (`FadeIn(shift=
  0.2*LEFT)`), also dim. Caption: `20 bytes, checksum at the end`. Anchor numbers this stage:
  `0x6bd`, `20 bytes`. Not shown: polynomial, `af a7`, byte offsets.
- Return: camera moves in on `bd`; dim all else. Carry-over frame: `bd` large, centred.

### Stage 4 — bits (S03 first part, ~5 s)
- `bd` → `TransformFromCopy` into eight squares `1 0 1 1 1 1 0 1` (`LaggedStart`, lag 0.5 so
  each bit is seen landing; `ONE`/`ZERO` colours). Label `MSB first`.
- Pull-back 3 (brief): the whole air frame as a thin dim strip of ~200 unlabelled ticks (no
  preamble/sync hex), with our eight bits boxed; hold 1 s; return to the eight squares.
  Caption: `8 of about 200 bits`. Anchor number this stage: `about 200 bits`.

### Stage 5 — tones (S03 rest, ~13 s) — **aha #1, spend the most effort here**
- Layout: eight squares top; I/Q circle (ComplexPlane, radius ~1.5) centre-left; frequency-
  vs-time axes below, x = 8 bit periods (no µs ticks), y with two levels labelled `+39 kHz` /
  `−39 kHz` (exact 39.06 = 40 MHz/1024 and the 32.2 µs bit period live in comments,
  `d8tone.c`).
- One `ValueTracker t` drives everything. For each bit (1 s screen time each, `linear`):
  the square stretches down into its segment on the time axis; the phasor rotates CCW for a 1,
  CW for a 0 (`always_redraw` arrow + `TracedPath` with `dissipating_time`); the step trace
  draws across the segment in the bit's colour. The 0 → 1 transitions (bits 2 and 7) are
  where the viewer sees the direction flip; do not speed through them.
- Caption while it runs: `1 spins one way, 0 the other`. Small corner label `slowed down`
  (no factor). Anchor number this stage: `±39 kHz` only.
- Pull-back 4 (the reveal): the eight segments slide left to become one short waveform; a
  winding-frequency dot sweeps the x-axis of a new spectrum axis beneath (−60…+60 kHz) and
  the balance curve draws itself: two spikes at ±39 kHz (3 s). Caption: `two tones, 39 kHz
  apart from centre`. Hold 2 s. Then return to the phasor circle, which is the carry-over object.
- Decision: 2D unless the helix (time as third axis) is implemented well; a 3D phasor that
  only tilts the circle is worse than a flat one.

### Stage 6 — hopping (S04, ~15 s) — **aha #2**
- Start tight on one packet: the phasor circle shrinks (`ReplacementTransform`) into a small
  yellow block labelled `packet` sitting in one cell of a grid; axes labelled only `channel`
  and `time`. Camera is close; only ±2 cells visible.
- The packet copies itself to the next slot on a different channel — `TransformFromCopy` with
  path_arc, run_time 1.5; caption `next packet: new channel, about 9 ms later`. The hop-table
  formula, E8 identity and 0.39 ms retune stay in comments (`PROTOCOL.md`, experiments/07).
  Camera follows the packet (`move_to`).
- Pull-back 5 (slow, 3–4 s, `move_camera` with a small tilt): the full grid 47 channels × ~16
  slots appears; the lit cells form the E8 hop pattern; a faint line joins them in order
  (`Create(path, rate_func=linear)`). Caption: `47 channels, one hop every 9 ms`. Hold 2 s.
  Ambient rotation 0.02 while holding. Anchor numbers this stage: `47`, `9 ms`. Not shown:
  2404 MHz, 299.93 kHz spacing, channel indices.
- Return: camera flies back to the *current* packet cell (`Restore`), which is bright; the
  others fade to 0.25. Carry-over: the yellow packet block.

### Stage 7 — drone (S05, ~18 s)
- The packet block travels right along a dashed air path into a CC2500 outline on a small
  Tinyhawk silhouette (`MoveAlongPath`, 1.5 s). The CRC pulse runs again over a tiny copy of
  the row; the check bytes turn green with a tick; caption `checksum ok`.
- Reverse of stages 4–3 in one fast motion (2 s): bits → `bd` → `0x6bd` → `1150` (same
  Transforms, reversed order), landing in a Betaflight channel list `A E T R`; `T = 1150` lit,
  others dim and without values. Caption: `flight controller reads throttle 1150`.
- `1150` splits into four equal copies (`TransformFromCopy`, lag 0.1) that fly to the four
  motor positions on a simple 3D quad; props begin spinning (`Rotate` with `linear`, rate ∝
  throttle); the quad lifts ~0.3 units (`shift(UP)`, `smooth`, 2 s). Caption: `mixed into 4
  motors`. Hold 2 s. End frame: quad hovering, number `1150` faint under it. Anchor number
  this stage: `4 motors`. Not shown: Betaflight version, board names, DShot, PID terms.

## 3. Checklist before rendering a scene
- Is the piece on screen in every frame except during a pull-back? If not, add it.
- Does every new representation arrive by a Transform from the previous one (not FadeIn)?
- Is everything that is not the piece at ≤ 0.35 opacity while it moves?
- Does every caption appear with its object, ≤ 8 words, and have ≥ 1 s hold after it?
- Are time-like motions `linear` and spatial moves `smooth`?
- Is there at most one pull-back per scene, 3–4 s, followed by a return?
- Do every number and colour come from the repo and `common.py`?
- Number budget: the piece's number plus ≤ 2 anchor numbers per stage, round forms in
  captions, everything else in comments or dimmed. Count the legible numbers in the frame.

## 4. Look: the exact hexes, fonts and strokes (what `common.py` implements)

Sources: `3b1b/videos/custom_config.yml` (background `#000000`, text font `CMU Serif`, output
saturation 1.5) and `3b1b/manim/manimlib/default_config.yml` `colors:` (the BLUE/TEAL/GREEN/
YELLOW/RED/GREY families). Reference frame: `frames/ref/fourier_thumb.jpg`. Manim CE ships the
same hex values under the same names, so `BLUE_C`, `GREY_B` etc. from `from manim import *` are
his colours; `common.py` gives them *role* names and the scenes only use those.

**Background** `#000000`, pure black (not the old `#0f1117`). His default manimlib config has
`#333333` but every published video overrides it to black.

**Palette (role → manimlib name → hex).** Nothing outside this list on screen.
- piece we follow `YELLOW_A` → YELLOW_C `#FFFF00` (1150, bd, the packet block, the hop path)
- host / app / bit 1 `BLUE_A`, `ONE` → BLUE_C `#58C4DD`; secondary blue `BLUE_DK` → BLUE_D `#29ABCA`
- mechanical / drone `BLUE_LT` (alias `PURPLE_A`) → BLUE_B `#9CDCEB`; no purple, no orange
- ok / checksum good `GREEN_A` → GREEN_C `#83C167`
- bit 0 / RF / check bytes `RED_A`, `ZERO` → RED_C `#FC6255`
- captions `INK` → WHITE `#FFFFFF`; labels, braces, axes `MUTED` → GREY_B `#BBBBBB`;
  outlines of boxes we are not following `STRUCT` → GREY_C `#888888`; grid lines `GRID` →
  GREY_D `#444444` at `stroke_opacity` 0.4–0.6; dimmed objects `set_opacity(DIM)` = 0.3.

**Fonts.** Everything is LaTeX, Computer Modern, through `common.py`: `caption()`/`caption_at()`
and `label()` are `Tex` (CM roman, upright; words and units: `µs` → `$\mu$s`); `num()` is `Tex`
digits for decimal quantities (`1150`), the same face as `Integer`/`DecimalNumber`, so a
counted number and its final still match; `mono()` is `\texttt{}` (CM typewriter) for hex,
bytes and bits (`0x6bd`, `bd`, `1 0 1 1`). `tex_escape()` turns plain strings with `µ − ± × ·
✓ → ≈ %` into LaTeX, so scene code keeps writing plain text. No `Text(font=...)`: Menlo and
Helvetica are gone. Sizes: caption 32, labels 20–24, hero number 64–72, byte-cell hex 20.
Each distinct string compiles once and is cached in `media/Tex`, so render time is unchanged
after the first run; a counting number must be an `Integer`/`DecimalNumber` (cached per glyph),
never an `always_redraw(Tex(...))`.

**Strokes and fills** (frame units; CE scales them with resolution, 480p and 1080p match):
`SW_THIN` 1 for cross hairs, grid, dashed guides; `SW` 2 for boxes, axes, circles, braces;
`SW_LINE` 3 for the line we follow (trace segments, arrows, hop path); `SW_FLASH` 5 only inside
`ShowPassingFlash`. Boxes have no opaque fill: `fill_opacity` ≤ 0.2 (bit squares 0.1, a pressed
key 0.2, bars 0.5 at most). The single filled object is the packet block (the piece), yellow,
opacity 0.9, no stroke, square corners. Rounded corners only on the key cap. No drop shadows,
no outlines around text.

**Composition.** One hero object large (key cap 1.8 units, hero number 72), everything else
small; empty black around it; captions at `to_edge(DOWN, buff=0.5)` (or `caption_at(frame)` in a
moving-camera scene); labels `next_to` their object with buff 0.15–0.25.

**Motion.** `rate_func=smooth` (the default) for every spatial move; `linear` only for the bit
cursor, counting, and time-like traces. Text arrives with `Write`, lines and boxes with `Create`,
whole groups with `FadeIn`; objects we stop following go to `DIM` rather than disappearing.

**3D objects** (the quad in S05): fills from the blue family only (`BLUE_E` body with a thin
`BLUE_A` outline, `BLUE_A` motors, `BLUE_DK` arms), props as `SW_LINE` white lines; no grey
solids.

**Where the tokens are used.** `common.py` holds palette, strokes and the text helpers;
`parts.py` (map strip, bracketed packet row, 160-bit unroll, 2-FSK wave) only consumes them.
Before/after proof frames: `frames/before/`, `frames/after/` (S01, S04, plus
`compare_S04_before_after_ref.png` against `frames/ref/fourier_thumb.jpg`), full cut contact
sheet `frames/v3/sheet_final.png`.


## Revision 3 implementation notes

The owner’s third revision supersedes the older stage sketches above where they differ:
S01 is a simplified Sticks page (two gimbals, central drone, eight named channel bars and
brief key map), not an isolated key. The yaw/pitch/roll demonstrations are illustrative;
we return to the exact throttle value before encoding. S03 explicitly introduces the
carrier before the small additive frequency offsets (about 1 in 60,000; the drawing
exaggerates that deviation). S04 shows bind agreement, synchronized TX/RX, narrow-channel
listening and an isolated noisy lane, then directional packet flow collapses into a stream
rectangle. S05 unrolls that same stream into the wave on the receiver side, then inversely decodes it.
Captions are 32; the parked map uses scale 0.85, box labels 18 and segment labels 16.
