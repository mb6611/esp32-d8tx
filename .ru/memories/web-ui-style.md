---
name: web-ui-style
description: Read before changing the look of any web page in this project (host/web/*, e.g. d8live); the user's style requirements.
load: description
paths: host/web/**
---
Web pages here should look like the user's write-up (docs/devkitv1/writeup/index.html): white paper, serif title, sans labels, mono numbers, thin grey rules, plain and hand-made. No gradients, glows, glassy cards, emoji, rounded-everything, filler or marketing copy.

**Why:** the user asked for the d8live page to match the blog's look and not read as generic AI-generated UI (Nov 2026).
**How to apply:** check host/web/d8live/src/theme.css for the design tokens before inventing colours or fonts.
