# Research: how good RE/hardware repos present work, docs layout, and publishing a static writeup

Read-only web research, 2026-11. Three questions: (1) how respected reverse-engineering /
hardware-hacking projects present their work (figures, count, repo<->writeup linking);
(2) developer-docs structure for a firmware + TS + Python + bench-evidence monorepo;
(3) hosting a single static HTML writeup next to a Cloudflare Workers app, plus interim options.

Existing repo layout observed (for context only): `docs/{devkitv1,validation,PROTOCOL.md}`,
`protocol/{captures,vectors,PROTOCOL.md}`, `bench/{d8-tx,cc2500-rxdiag,register-map,...}`,
`firmware/`, `packages/{core,serial,ui}`, `apps/{web,desktop}`, `python/d8tx`.

---

## 1. How well-regarded projects present their work

### Patterns by exemplar

| Exemplar | Form | Figures used | Repo <-> writeup link |
|---|---|---|---|
| esp32-open-mac (Jasper Devreker) — https://esp32-open-mac.be/ , long-form origin post https://zeus.ugent.be/blog/23-24/open-source-esp32-wifi-mac/ | Numbered blog series (`posts/0001-introduction`, `0003-faraday-cage`, `0005-the-road-ahead`) on a project domain; repo is code-only | Few figures, all explanatory: one OSI block diagram, bench photos (dongle + two 30 dB attenuators; paint-tin Faraday cage with copper tape and ferrites), a checklist roadmap (☑/☐). No spectrograms. | Repo README first paragraph says "see <blog> for how this was done"; blog "Code" section links the GitHub org. https://github.com/esp32-open-mac/esp32-open-mac |
| Samy Kamkar OpenSesame — https://samy.pl/opensesame/ , repo https://github.com/samyk/opensesame | Single long HTML page on his own site; repo README is a shortened copy that points back ("More details at sa.my/opensesame/") | Demo GIF at top, one diagram (De Bruijn), arithmetic shown inline as the "figure". Headline numbers (29 min -> 8 s) carry the story. Explicit **Prevention** and **Criminals** (responsible-use) sections near the top. | Page: "Source code: github URL" line under the fold; repo homepage field set to the page. Video at top. |
| Michael Ossmann / GSG — "Rapid Radio Reversing" https://greatscottgadgets.com/2015/12-29-rapid-radio-reversing-toorcon-2015/ ; SDR lesson 11 (inspectrum spectrogram) https://greatscottgadgets.com/sdr/11/ ; Black Hat whitepaper with gr-fosphor waterfall https://blackhat.com/docs/us-17/wednesday/us-17-Ossmann-Whats-On-The-Wireless-Automating-RF-Signal-Identification-wp.pdf ; tech report https://greatscottgadgets.com/tr/gsg-tr-2016-1.pdf | Talk + slides + short post; formal findings as numbered PDF *technical reports* (gsg-tr-YYYY-N) | Spectrogram/waterfall of the capture is the canonical RF figure; inspectrum with cursors to read symbol period; photos of the target device opened up | Post links slides/video; TR PDFs are the citable artifact |
| RF reversing blogs (rtl-sdr.com, xakcop) — https://www.rtl-sdr.com/reverse-engineering-signals-universal-radio-hacker-software/ , https://xakcop.com/post/re-2.4ghz/ , https://labs.portcullis.co.uk/blog/adventures-in-rf-using-inspectrum-to-analyse-fsk-and-askook-signals/ , https://x8x.net/2016/12/11/christmas-with-rfcat/ | Single post per target | Standard figure sequence: (a) wideband waterfall showing bursts/hop pattern; (b) zoomed inspectrum spectrogram with **derived frequency plot** for FSK and **cursors** over one symbol period; (c) demodulated bit string / URH packet table with fields colored; (d) hex dump with diff between button presses. 3–6 figures typical. | Code as gist or small repo linked inline |
| PoC\|\|GTFO / Travis Goodspeed — https://nostarch.com/gtfo2 , issue 0 https://mcfp.felk.cvut.cz/publicDatasets/pocorgtfo/contents/issue00.pdf | Short articles whose standard is "here is a working PoC"; prose + minimal listings; polyglot PDFs as the artifact itself | Very few figures; code listings and hex dumps instead. Register-level facts stated as tables. | The article *is* the artifact; code embedded or in a one-file repo |
| bunnie's blog — https://www.bunniestudios.com/blog/2014/an-oscilloscope-module-for-novena/ , teardown posts e.g. https://www.bunniestudios.com/blog/2008/sony-xel-1-oled-tv-teardown/ | Blog posts, heavy on photos | High-res board photos (click for full-res), scope captures, annotated die/board shots | Links to repo/wiki per project |
| Ben Eater — https://eater.net/8bit , schematics page https://eater.net/8bit/schematics | Project site: overview page -> one page per module -> dedicated **schematics/KiCad page** | Schematics and timing diagrams; video per module | Site is primary; files downloadable from the site |
| Fabrice Bellard — https://bellard.org/ , e.g. https://bellard.org/pi-challenge/index.html , https://bellard.org/ioccc_lena/ | One flat HTML page per project: ~1-paragraph abstract, results table, download links, references | Almost none; a results table or one output image | Tarball/download link on the page; no GitHub |
| Bartosz Ciechanowski — https://ciechanow.ski/gps/ | Single very long page; prose interleaved with live WebGL/JS models the reader drags; no repo | Every figure interactive; progressive build-up from toy model to real system | N/A (no code published); see https://learn-ui.com/chapters/explaining/explorable-explanations |
| Hackaday.io projects — https://hackaday.io/project/46/logs , quickstart https://cdn.hackaday.io/files/492872108695008/Profile%20%26%20Project%20Quickstart%20for%20Hackaday%20io.pdf ; Hackaday-featured CC2500 RC hack https://hackaday.com/2015/09/20/hacking-2-4ghz-radio-control/ -> https://befinitiv.wordpress.com/2015/08/26/enable-2-4ghz-rc-systems-to-work-with-2-4ghz-video-systems/ | Stable **Details** overview + dated **Logs** (one per milestone, goal -> change -> evidence -> lesson) + Build Instructions + Files | Cover photo, block diagram, scope/SPI captures, photos of wiring | Files section links external repo |
| USENIX/WOOT artifacts — https://www.usenix.org/conference/atc25/call-for-artifacts , https://www.usenix.org/conference/woot26/call-for-artifacts , https://secartifacts.github.io/woot2023/index , ACM badging https://www.acm.org/publications/policies/artifact-review-and-badging-current/ | Repo README with two mandated sections: **Getting Started** (≈30 min smoke test) and **Detailed Instructions** (experiment-by-experiment, expected output, how to compare to the paper's figures) | Figures live in the paper; README maps each claim/figure to a script | Paper PDF included in the artifact; badges: Available / Functional / Results Reproduced |

### Which figures, and how many
- RF-protocol writeups converge on **3–6 figures**: wideband waterfall (hop pattern / channel usage) ->
  zoomed spectrogram of one packet with symbol cursors -> demodulated bits/packet table ->
  one bench photo. Constellation and eye diagrams are rare in hobbyist RE writeups (they appear in
  GSG/academic material); they're worth including only if they show something a spectrogram can't
  (e.g. modulation-index / deviation accuracy of a software-generated FSK).
- Timing diagrams (packet period, hop dwell, TX->RX latency) are shown as annotated spectrograms or
  simple ASCII/SVG timelines, not scope screenshots, unless a scope was the instrument.
- Reliability/latency **CDFs or histograms** appear in academic artifacts (USENIX style), not in blog
  RE writeups; one CDF of packet-success vs. distance/attenuation or hop-timing error is a
  differentiator for a "validation" section and fits the repo's `docs/validation/`.
- Bench photos: 1–2, captioned with what each component is (esp32-open-mac captions attenuator values).
- Headline numbers in bold near the top (Kamkar), a roadmap checklist (esp32-open-mac), and an
  explicit "what's unresolved / not measured" list are the recurring prose devices.
- Responsible-use / regulatory text goes **near the top**, not in a footnote (Kamkar's Prevention +
  Criminals sections).

### Repo <-> writeup linking, observed
1. **Project domain + numbered posts, code-only repo** (esp32-open-mac): README para 1 links the
   writeup; writeup "Code" section links the repo.
2. **Single HTML page on personal site, README = abridged copy** (Kamkar): repo `homepage` field set,
   "Source code:" line on the page.
3. **GitHub Pages from `docs/`** (common; GitHub supports root or `/docs` of a branch:
   https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
4. **Artifact README that maps figures to scripts** (USENIX): writeup is the paper; README says
   "Figure 3 <- `scripts/fig3.py`".
Pick 1 or 3 for this repo; keep the README short with a "Read the writeup ->" link at the top.

---

## 2. Developer-docs structure for this monorepo

Sources: Diátaxis https://www.diataxis.fr/start-here/ and https://diataxis.fr/application/
(explicitly "a content framework, not a mandated folder structure"); matklad ARCHITECTURE.md
https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html (map of the codebase: where each thing
lives, key invariants, "architecture invariants" and cross-cutting concerns, kept short and
link-free so it doesn't rot); Google README guide https://google.github.io/styleguide/docguide/READMEs.html
(READMEs are short summaries at every navigable level, linking to fuller docs; one source of truth);
GitHub README notes https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes
(use relative links so they work in clones/branches).

Recommended layout (adapts what already exists):

```
README.md              what it is, headline result, regulatory note, link to writeup, 5-line quickstart, map of folders
ARCHITECTURE.md        matklad-style: data flow host->firmware->CC2500 air->E8; package boundaries; invariants
CONTRIBUTING.md        toolchain pins, how to run each test tier (TS unit, Python vectors, firmware, bench)
docs/
  index.md             one-screen map by Diátaxis quadrant
  tutorials/           "flash the DevKit and bind to an E8 in 20 min"
  how-to/              flash, recover a hung board, record a capture, run the Python decoder, run bench scripts
  reference/           PROTOCOL.md (the spec), UART host protocol, register map, CLI/API of packages
  explanation/         why D8 on an ESP32 works, hop scheme, regulatory framing (§15.249 text), limits
  validation/          one page per measured claim: setup photo, method, figure, raw-data path, date, unresolved
protocol/              spec + golden vectors + captures (data, not prose) — reference/PROTOCOL.md should be the
                       only prose copy; make docs/PROTOCOL.md a stub that links here (currently duplicated)
bench/<exp>/README.md  one README per experiment: goal, setup, command, result file names, what to look for
packages/*/README.md   purpose, status, install, 10-line usage, link to docs/reference
firmware/README.md     board, pins, build/flash/monitor, recovery
python/README.md       already exists; keep as the reference implementation's quickstart
```

Where things live:
- **Protocol spec** = reference material -> `protocol/PROTOCOL.md` as single source, linked from
  `docs/reference/`. Golden vectors next to it so spec and vectors version together.
- **Validation results** = explanation+reference hybrid -> `docs/validation/` prose, with figures
  rendered from raw data in `bench/<exp>/` by scripts (USENIX "figure <- script" mapping). Each page
  states what was *not* measured (consistent with the project's accuracy stance on harmonics/EIRP).
- **Bench procedures** = how-to -> live beside the scripts in `bench/<exp>/README.md`; `docs/how-to/`
  links rather than copies.
- Per-package READMEs stay under ~60 lines; anything longer moves to `docs/` (Google guidance).

---

## 3. Publishing one static HTML writeup beside the Workers app

Facts verified from Cloudflare/GitHub docs:

- **Workers static assets, same origin.** Put `writeup.html` (or `writeup/index.html`) in the
  assets `directory`. With `not_found_handling: "single-page-application"`, any request that
  *matches a real file* is served as that file, and only non-matching navigations fall back to
  `index.html` — so `/writeup/` works with zero Worker code. For explicit control use
  `assets.run_worker_first: ["/api/*", "!/writeup/*"]` (Wrangler ≥ 4.20) and/or `env.ASSETS.fetch()`
  in the Worker. https://developers.cloudflare.com/workers/static-assets/routing/single-page-application/ ,
  https://developers.cloudflare.com/workers/static-assets/binding/ ,
  https://developers.cloudflare.com/workers/static-assets/routing/static-site-generation/
  Caveat: a Vite SPA build may not copy a stray HTML file; place it in `public/` so it lands in `dist/`.
- **Cloudflare Pages, separate project.** Direct Upload: `npx wrangler pages deploy <dir>` (≤20,000
  files, 25 MiB each) or dashboard drag-and-drop (≤1,000 files); `--branch=<name>` gives
  `<branch>.<project>.pages.dev` preview aliases; production at `<project>.pages.dev`. Cannot switch a
  Direct Upload project to Git integration later. https://developers.cloudflare.com/pages/get-started/direct-upload/ ,
  https://developers.cloudflare.com/pages/configuration/preview-deployments/
  Note: Cloudflare now steers new static projects to Workers static assets; Pages is still fine for a
  single-page writeup and gives an independent URL before the app ships.
- **GitHub Pages.** Publish from `/` or `/docs` of a branch, or via Actions. Pages sites are public
  even if the repo is private, and Pages on a *private* repo needs a paid plan — not usable until the
  owner flips the repo public anyway. https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- **raw.githack.com** proxies a GitHub file with correct `text/html` (raw.githubusercontent serves
  `text/plain`); `raw.` = dev (no cache), `rawcdn.` = CDN pinned to a commit. Public repos only.
  https://raw.githack.com/
- **htmlpreview / html-preview.github.io** renders a GitHub HTML via a CORS proxy, client-side;
  public repos only; flagged as a security risk for anything with scripts/storage.
  https://html-preview.github.io/ , https://github.com/html-preview/html-preview.github.io

### Recommendation
1. **Final:** same-origin `/writeup/` served as a static asset from the Workers app (one deploy, one
   domain, shareable URL, no routing code). Add `!/writeup/*` to `run_worker_first` only if the Worker
   is ever made to run first for other routes.
2. **Interim, repo still private:** a throwaway Cloudflare Pages Direct Upload project
   (`wrangler pages deploy docs/writeup --project-name d8tx-writeup`) — private-repo friendly, free,
   gives `<project>.pages.dev` plus `--branch` previews for drafts. Delete it after the app deploys,
   or keep it as the canonical "paper" URL and link both ways.
3. **Interim, local only:** keep the writeup as a self-contained `docs/writeup/index.html` with
   inline CSS and relative image paths; `python -m http.server` to review. Once public, GitHub Pages
   from `/docs` or raw.githack become free extra mirrors, but don't rely on them for the canonical link.
4. Make the writeup self-contained (inline CSS, local images, no CDN JS) so the same file works in all
   three places; Kamkar/Bellard-style single page, 3–6 figures, headline numbers + regulatory section
   near the top, "Code:" link to the repo and "Validation data:" link to `docs/validation/`.
