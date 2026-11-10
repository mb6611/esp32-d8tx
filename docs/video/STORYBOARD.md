# d8tx: from a key press to motor thrust (rough cut)

Target: about 110–120 s total (revision 3 cut about 117 s), 1080p later, rough cut at -ql (480p15). Manim Community 0.22,
venv `docs/video/.venv` (`docs/video/.venv/bin/manim`). Style and helpers: `docs/video/common.py`
(import with `from common import *`). Every number on screen must come from the repo
(cite the file in a comment). No narration; short on-screen captions, calm and plain
(no hype, no exclamation marks).

Real facts to use (verify against the files named):
- Keyboard: W raises throttle, capped (15% cap = 1150 µs in experiments/14); sticks are
  channel values 1000..2000 µs. Arm is channel 7 (AUX3, 1700..2100 µs).
- Packet: FrSky D8 data packet built by `firmware/main/packet.c` (`d8_build_*`): length byte
  0x11, txid0, txid1, counter, ..., 8 channel values packed 12 bits, then CRC-16 appended.
  Test vector body from experiments/05-first-packet/data/NOTE.md:
  `11 42 b2 00 00 01 ca ca ca ca 88 88 ca ca ca ca 88 88`, CRC `af a7`. 208 bits on air
  (preamble + sync + payload + CRC; see packet.c / tools/d8-tx-host for the exact layout).
- Bits to tones: 2-FSK at ~31,044 baud; bit 1 = test tone +1 step, bit 0 = −1 step;
  one step = 40 MHz/1024 = 39.06 kHz (stock D8 deviation is ±31.7 kHz). The ESP32 keys its
  built-in test tone (`rom_start_tx_tone_step`); see experiments/04, 05 and firmware/main/d8tone.c.
- Hopping: 47 channels, one packet per 8.994 ms slot; channel n = 2404.000 MHz + n × 299.93 kHz;
  hop table entry 0 = 0 (bind channel), entry i = (start + step·i) mod 256 (protocol/PROTOCOL.md);
  E8 identity `42b2 2 55` (start 2, step 55). Retune takes at most 0.39 ms (experiments/07).
- Drone: Tinyhawk 3, MATEKF411RX, CC2500 receiver, Betaflight 4.2.11. Receiver checks CRC,
  Betaflight maps channels (AETR: roll, pitch, throttle, yaw), PID + mixer → 4 motor outputs
  (DShot), props spin. In 08 a one-second full-throttle pulse lifted the drone off the bench.

Scenes (file `scenes/sNN_name.py`, class `SNN`; one piece is followed the whole way, see STYLE-3b1b.md; the last
frame of each scene and the first of the next are built from the same helper (`common.py` / `parts.py`) so the cut is
invisible). A MAP STRIP (`parts.MapStrip`) sits at the top edge of every frame: keyboard - browser - USB - ESP32 -
2.4 GHz air - drone (CC2500 | SPI | flight ctrl | motors), dim, with a bright marker showing where the data is right
now; each physical hand-off opens the strip, moves the marker along the segment, and closes it again.
- S01 `s01_key_to_stick.py` (~17 s): simplified Sticks page: left yaw/throttle and right roll/pitch gimbals,
  centre drone, THR AIL ELE RUD AUX1 AUX2 ARM AUX4 bars, brief key map. Both gimbal dots move at the same
  time; the illustrative drone climbs, turns and tilts with them, the four stick bars move together and the
  key caps light. Then `Let's focus on the throttle`: the other bars dim, throttle settles at 1150 in yellow,
  ending at the shared `hero_number`.
- S02 `s02_packet.py` (~22 s): `1150` -> serial line -> USB/ESP32 -> `0x6bd` -> bracketed 20-byte packet.
  Individual hex glyphs fly once into throttle cells, without a second overlapping source; whole packet
  unrolls into 160 bits and the camera returns to the throttle byte.
- S03 `s03_tones.py` (~19 s): channel/carrier about 2.4 GHz first; bit adds/subtracts 39 kHz, about
  one in 60,000 (wave exaggerated). Cursor squeezes/stretches wave. Hop redraws the same modulation on
  the next carrier/channel; ends on the shared centred wave.
- S04 `s04_hopping.py` (~26 s): wave -> packet; TX and RX follow the hop order agreed at bind,
  landing together. Pull back to 47-channel grid with arrows joining packets. Receiver listens to one
  narrow channel, rejecting off-channel noise/interference. Illustrative one noisy lane loses one of
  47 packets, not the link. Collapse all packet blocks into one continuous-stream rectangle.
- S05 `s05_drone.py` (~28 s): same stream rectangle and caption -> drone CC2500 -> inverse decode:
  wave -> bits -> packet -> checksum -> SPI -> flight controller -> 0x6bd -> throttle 1150 -> motors.
  Props spin and illustrative 3D quad lifts.

Fact qualifications: the 1-in-47 loss is an illustrative single-channel interferer, not a measured loss
rate or immunity to wideband interference. Experiments/04 demonstrates noise dependence on 102/203/812 kHz
filter settings; experiments/15 establishes transfer/storage of the hop table at bind. The slot timing
is maintained during normal link operation, not a permanent clock synchronization established by binding.
The opening orientation changes and final low-throttle lift are explanatory cartoons, not measured flight
responses at 1150 µs. Actual bench lift in experiment/08 used full throttle.

Rendering: `cd docs/video && .venv/bin/manim -ql --disable_caching -o SNN scenes/sNN_name.py SNN`
(output lands under docs/video/media/videos/...). Stitch: `docs/video/stitch.sh`.

## Revision 4 note (S03 / S04 seam)

S03 is now the modulation diagram in three stacked rows under the throttle's eight bits: the
bit signal as a frequency offset (`+39 kHz` / `−39 kHz`), `+` channel A's carrier
(`2.404 GHz`, hop channel 0), `=` the 2-FSK wave. The sign is a plus because FSK shifts the
carrier's frequency; nothing is multiplied. On the hop the carrier and the result squeeze
together into channel B (`2.421 GHz`, hop channel 57; 5 cartoon cycles per bit against A's 3),
same bits. The result wave then gets a yellow box and shrinks into the packet block, so the
wave-to-packet hand-off is in S03 and S04 opens on the block (`packet_block_big()` centred).
