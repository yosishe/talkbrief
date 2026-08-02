# Architecture

```
URL ─▶ fetch ─▶ slides ─▶ transcript ─▶ align ─▶ synthesize ─▶ verify ─▶ render
```

Seven stages, each with one on-disk JSON contract (see `src/talkbrief/schemas.py` —
the schemas ARE the documentation of every artifact). A stage re-runs iff it never
completed, its parameters changed (per-stage config hash in `manifest.json`), it is
`--force`d, or an UPSTREAM stage re-ran (downstream invalidation).

## Run directory

```
<outdir>/<video_id>__<slug>/
├── manifest.json            # stage statuses + config hashes + tool versions
├── meta.json                # distilled video metadata + caption provenance
├── media/video.mp4          # ≤720p (measured: 1080p ≈ 2.8× bytes, no OCR gain)
├── captions/cap.<lang>.json3
├── transcript/transcript.json
├── slides/slides.json + slide_NNN.jpg
├── align/alignment.json
├── digest/digest.json + calls/<label>_{request,response}.json   # full LLM I/O kept
├── verify/verified.json     # digest + per-quote {t, grounded, match_source} + stats
├── report/report.html [+ report.pdf] [+ assets/]
└── run.log
```

## The detector (slides.py)

Union of two detectors — stability-segmented dhash matching against ALL kept slides,
plus a fixed 45 s floor that cannot be fooled by the (measured) inverted hash metric
on composited video. Build sequences collapse to the final build; floor duplicates
dedup by OCR-token overlap. No motion masks, ever (measured trap).

## The LLM seam (llm/)

`LLMBackend.generate_json(LLMRequest) -> LLMResult`. v1 = `ClaudeCodeBackend`
(`claude -p --output-format json --json-schema <inline> --tools Read
--permission-mode dontAsk --no-session-persistence --disable-slash-commands
--strict-mcp-config --max-budget-usd X`), images as cwd-relative paths the model
Reads. Success is judged by `is_error` (a live probe returned `subtype:"success"`
WITH `is_error:true`). `FakeBackend` runs the whole pipeline offline for tests;
`AnthropicAPIBackend` is a documented v2 stub.

## Trust chain

The model writes verbatim quotes, never timestamps. `verify.py` anchors each quote
(exact → ellipsis-fragments → fuzzy ≥0.90 with digit-exact equality → slide-OCR
fallback) and stamps `t`. The renderer turns grounded quotes into deep-link chips
and flags ungrounded ones in amber. Hard-token recall (numbers+units, versions,
acronyms, flags) is reported in the footer with the min-count filter applied to
both sides of the fraction.
