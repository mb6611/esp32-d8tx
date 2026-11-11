---
name: video-narration-pronunciation
description: Read before changing the narrator voice, respellings or narration text of the docs/video Manim explainer; how the owner wants pronunciation checked.
load: description
paths: docs/video/**
---
A whisper transcript matching the script does not prove a word is pronounced right. For names and acronyms, check the phonemes the TTS produces and give the owner a clip to listen to.

**Why:** on 2026-11-10, after the swap to Kokoro (voice am_michael, the owner's pick), whisper "heard" Fourier correctly from the respelling "Foo-ree-ay", but the owner listened and said it was mispronounced. It was fixed with a misaki phoneme override in `common._SPOKEN`.
**How to apply:** when a word needs a respelling, compare candidates by their phoneme strings (Kokoro `result.phonemes`), prefer an inline phoneme override over a creative respelling, and save the clip for the owner. The owner wants UART heard as "you-art".

On 2026-11-10 the owner also asked for "Gaussian" as GOW-shun ("sh", not GOW-see-un) and rejected a short sentence whose pitch rose at the end like a question. For the ElevenLabs voice, which gives no phonemes, check a clip with a phoneme recogniser and the pitch contour of the sentence end; the scripts used are in `docs/video/frames/v13/audio/` (check they still exist).
