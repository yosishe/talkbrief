# Changelog

## Unreleased (v0.1.0)

- Full pipeline: fetch → slides → transcript → align → synthesize → verify → render.
- Union slide detector (stability dhash + 45 s floor), build collapse, OCR ladder
  (Apple Vision → tesseract → none).
- Claude Code CLI backend (no API key), FakeBackend for offline runs, API stub for v2.
- Mechanical quote verification (digit-exact fuzzy, ellipsis-aware, slide-OCR
  fallback) + hard-token recall.
- Single-file interactive HTML report (light/dark, TOC scroll-spy, lightbox, j/k,
  YouTube deep-link quote chips), full Hebrew RTL mode, weasyprint PDF extra.
- Batch mode with FINAL/RETRYABLE failure classification, per-stage resume with
  downstream invalidation, `doctor` preflight.
