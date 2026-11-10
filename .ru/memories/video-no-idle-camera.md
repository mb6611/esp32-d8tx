---
name: video-no-idle-camera
description: Read before adding idle motion, pacing fixes or camera moves to the Manim explainer scenes in docs/video.
load: content
paths: docs/video/**
---
Never move the camera (zoom, push-in, drift, shift) to fill time while the narration talks. The camera moves only for a deliberate, storyboarded change of view. A still frame under speech is fine; if motion is wanted, put it on the objects and tie it to the words (wave flows, packets stream, the named cell pulses).

**Why:** on 2026-11-10 a fix round added slow camera push-ins to pass an ffmpeg freezedetect threshold; the owner watched it and said "why is it just randomly zooming in and out while it's talking, it's confusing".
**How to apply:** do not give scene authors a "no frozen frame longer than N s" target measured by freezedetect; it rewards camera drift. Judge idle stretches by eye instead.
