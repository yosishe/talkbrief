# talkbrief

**Turn a YouTube talk into a grounded, slide-by-slide interactive brief.**

`talkbrief` watches the talk so you can *read* it: it deterministically extracts the
unique slides, aligns them with the transcript timeline, has Claude write per-slide
notes and a whole-talk narrative — and then **mechanically verifies every quote**
against the transcript before you ever see it. The output is a beautiful,
self-contained HTML report where every claim links to the exact second on YouTube.

<!-- hero screenshot: docs/hero.png (generated from examples/report-sample.html) -->

```bash
pip install talkbrief
talkbrief doctor        # checks ffmpeg, yt-dlp, deno, and your Claude Code login
talkbrief run https://www.youtube.com/watch?v=zjkBMFhNj_g
open talkbrief-runs/*/report/report.html
```

No API key. `talkbrief` rides the **Claude Code CLI** you already have — if `claude`
works in your terminal, `talkbrief` works too.

## What you get

One self-contained `report.html` (opens offline, light/dark, keyboard `j`/`k`):

- **TL;DR + narrative** — the talk's actual argument, not a generic summary.
- **Slide cards** — every unique slide with: what it shows, what the speaker *said*
  while it was up (each point backed by a verbatim quote chip that deep-links to
  `youtu.be/…?t=<exact second>`), why it matters, and **"on the slide, not said
  aloud"** — the information you'd miss by only reading a transcript.
- **Chapters, glossary, key numbers & names** — all quote-anchored.
- **A grounding badge** — e.g. *"39/41 quotes verified against the transcript"*.
  Unverified quotes are flagged in amber, never silently dropped.

Plus `--pdf` export, `batch` mode for a file of URLs, `--lang he` for a fully
right-to-left Hebrew report, and per-stage resume (`talkbrief resume <dir>`).

## Why another slide extractor?

| | slides | transcript align | LLM notes | quote verification | interactive report | no API key |
|---|---|---|---|---|---|---|
| [video2slides](https://github.com/binh234/video2slides), [video2pdfslides](https://github.com/kaushikj/video2pdf), [vid2slides](https://github.com/patrickmineault/vid2slides) | ✅ | — | — | — | — | n/a |
| [slidegeist](https://pypi.org/project/slidegeist/) | ✅ | ✅ | captions via local llama.cpp server | — | markdown | needs 2 local servers |
| [lecture2notes](https://github.com/HHousen/lecture2notes) (academic, pre-LLM) | ✅ | ✅ | BART-era | — | — | n/a |
| NoteGPT / Lynote / Video Highlight (SaaS) | ✅ | ✅ | ✅ | — | closed | subscription |
| **talkbrief** | ✅ | ✅ | ✅ Claude | **✅ mechanical** | **✅ single file** | **✅ Claude Code** |

The two ideas that carry this tool:

1. **Deterministic pipeline, LLM only where language understanding is needed.**
   Download, frame sampling, slide detection, OCR, timestamp alignment — all plain
   code with on-disk JSON contracts you can inspect. The model only ever writes
   prose about material it was handed.
2. **Trust is a feature.** The model is never allowed to write a timestamp — it must
   copy verbatim quotes, and code locates each quote in the transcript (digit-exact:
   fuzzy matching that would accept "40 ms" vs "4 ms" is rejected) and stamps the
   time. What can't be located is visibly flagged.

## Requirements

- Python ≥ 3.11, **ffmpeg** on PATH
- **[Claude Code](https://claude.com/claude-code)** installed and logged in
  (`claude` CLI — the v1 LLM backend; an Anthropic-API backend is planned for v2)
- **deno** (current `yt-dlp` needs an external JS runtime for YouTube)
- Optional extras: `talkbrief[ocr]` (Apple Vision OCR on macOS — measurably cleaner
  than tesseract), `talkbrief[asr]` (faster-whisper for videos without captions),
  `talkbrief[pdf]` (weasyprint PDF export)

`talkbrief doctor` checks all of the above, including a real headless `claude -p`
probe — because a broken OAuth session is nicer to discover *before* a 40-minute
download, not after.

## How it works

```
URL ─▶ fetch ─▶ slides ─▶ transcript ─▶ align ─▶ synthesize ─▶ verify ─▶ render
       yt-dlp   ffmpeg+    json3 cues    windows   claude -p     quote     report.html
       ≤720p    dhash      (or ASR)      ×slides   map/reduce    anchoring (+ report.pdf)
```

Every stage writes one JSON artifact into the run directory and is independently
re-runnable; `resume` skips completed stages whose parameters didn't change.

Some design choices worth knowing about (each one carries a measurement from a
prior pipeline this tool's lessons come from):

- **The slide detector is a UNION of two detectors.** A perceptual-hash detector
  with a stability test finds most slides — but on composited conference video the
  hash metric can *invert* (the same slide at two moments measures farther apart
  than two different slides), so a fixed 45-second floor detector, which has no
  metric to fool, guarantees no long-held slide is ever missed. The union raised
  recall from 84.6% to 92.3% on a hand-built gold set. Duplicates the floor
  introduces are cleaned by OCR-text dedup afterwards. There is deliberately **no
  motion mask** (one destroyed 64 distinct code headlines on a screencast).
- **Progressive-build slides collapse to the final build**, keeping the fullest
  frame and the union of on-screen spans (a slide that returns later keeps both
  spans — the report shows "returned ×N").
- **Slides are routed by content**: text-rich slides reach the model as OCR text
  (~24× cheaper), diagrams and code reach it as images (`code` always as an image —
  OCR destroys indentation). Weak/empty OCR routes to the image channel, which is
  also what keeps non-Latin slides safe.
- **The transcript input is never chunked** — windows split the *output*, because a
  single call's output ceiling is real however large the context window is.
- **Caption provenance is recorded** (`manual` / `auto` / `asr`) — a manual track
  and an auto track are different artifacts and are never treated as equals.

## Hebrew mode

```bash
talkbrief run <url> --lang he --pdf
```

Produces a fully RTL report (`dir="rtl"`, logical CSS properties, bidi isolation
for LTR fragments) with Hebrew prose and verbatim original-language quotes.
PDF export goes through weasyprint — the rendering path that actually gets
Hebrew bidi right.

## Key options

| flag | default | |
|---|---|---|
| `--lang en\|he` | `en` | output language of the brief |
| `--pdf` | off | also export `report.pdf` (needs `[pdf]`) |
| `--asr off\|auto\|force` | `off` | local transcription when captions are missing (needs `[asr]`) |
| `--model NAME` | CLI default | passed through to `claude --model` |
| `--max-budget-usd X` | `3.00` | cap per LLM call |
| `--max-images N` | `24` | image attachments per LLM call |
| `--interval / --threshold / --stability / --floor-seconds` | `2.0 / 0.08 / 0.05 / 45` | detector tuning |
| `--embed auto\|always\|never` | `auto` | single-file report vs `assets/` folder (auto-falls back over 25 MB) |
| `--only / --force STAGES` | | run or re-run specific stages |

## Honest limitations

- The v1 LLM backend **requires a logged-in Claude Code CLI** (subscription auth or
  `claude setup-token`). If headless auth is broken, `talkbrief doctor` says so and
  tells you the fix.
- YouTube extraction breaks on a weekly cadence ecosystem-wide; keep `yt-dlp`
  fresh (`doctor` warns when yours is >60 days old).
- OCR quality differs per platform (Apple Vision > tesseract); weak OCR shifts
  slides to the image channel — costlier, not worse.
- Slide-heavy talks are the sweet spot. Speaker-only videos degrade gracefully to
  a transcript-only brief (with a visible notice), never a crash.

## Development

```bash
git clone https://github.com/yosishe/talkbrief && cd talkbrief
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest         # 54 tests, no network, no LLM — a synthetic ffmpeg
                         # fixture deck exercises every detector path
.venv/bin/ruff check src tests
```

The test fixture reproduces the nasty cases with *known* timings: a 95-second hold,
an A→B→A slide return, a build sequence, and a jittering slide the hash detector
cannot see (only the union floor catches it — that's the regression test for the
measured long-slide miss).

## License

MIT.
