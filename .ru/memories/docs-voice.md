---
name: docs-voice
description: Read before writing or rewriting any README, experiment README, report or writeup text for the d8tx/d8rx projects; the owner's voice rules.
load: description
---
Write like someone calmly explaining something complex very clearly (the owner's reference: Feynman in "Surely You're Joking, Mr. Feynman!"). First person "I", plain words, the reasoning shown step by step, explain an idea before any number, say what was known at the time vs learned later.

Never: punchy aphorisms or slogan lines ("Seven out of ten is a demonstration, not a radio link." was rejected: "I don't talk like this"), dramatic or hyped phrasing ("hinges on", "bugged me", "miraculously" when not the owner's own words), exclamation marks, bold for drama, walls of numbers.


Leave out process meta that isn't about the hardware: agents, plans/specs/pass marks ('verdict B', 'the plan asked'), task briefs, uncommitted changes or working-tree state, scratch paths, and documentation QA such as 'fresh clone in under ten minutes' (rejected as dumb, 2026-11-09). A README describes what was measured on the device and what it showed.

Also leave out ordinary software bugs in my own test tooling (e.g. a test firmware that rebooted from an unfed watchdog and was fixed before any keying): the owner said on 2026-11-10 they are general software bugs that shouldn't be included. Keep a bug only if it changed or explains a measured result; the logs stay in data/. When one is kept, open with the mechanism, not a verdict: "The long runs of misses were my firmware's fault." was rejected as stupid (2026-11-10); say what happened ("the ESP32 stopped transmitting for 0.22 s after every trigger while it sent a 20 KB capture over the UART").

**Why:** the owner rejected a first sample as "exaggerated in tone" and a second line as not how he talks (2026-11-09). Approved sample: esp32-d8tx experiments/05-first-packet/README.md (calm version).
Experiment READMEs must be technical: state the actual measurements and numbers in the prose (counts, rates, timings, the mechanism, e.g. '500 µs window vs CRC bytes arriving ~515 µs after the payload'), with the reasoning that connects them. Vague summary lines without numbers ('Within the precision of the counts, they're the same.') were rejected (2026-11-09); say what the numbers show instead ('132 of 140 (94%) vs 175 of ~189 (93%); the 95% intervals overlap').

**How to apply:** narrative in "I", technical and numeric but calm and clear; data descriptions as plain labels (no person); re-run steps as imperative commands. Keep the owner's own sentences when he wrote them. Approved style sample: esp32-d8tx experiments/06-fixed-channel-reliability/README.md.
