---
name: tx-writeup-layout
description: Read when adding TX material to the DevKit V1 project write-up or its HTML page.
load: description
paths: docs/devkitv1/writeup/**
---
For this private TX clone, keep **one continuous HTML write-up**: the original RX story followed by the TX chapter in `docs/devkitv1/writeup/index.html`. Do not create a separate TX HTML page. A separate Markdown `tx.md` can remain as the editable source for the appended chapter.

**Why:** The user corrected the first separate `tx.html` implementation on 2026-11-06 and explicitly wanted TX to continue the existing HTML write-up.
**How to apply:** Add or revise TX content by editing the chapter source, regenerate the marked section of `index.html`, and keep navigation pointed to its TX anchor. Preserve the historical RX account.
