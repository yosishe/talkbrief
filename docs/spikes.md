# M0 spikes — claude -p mechanics

Status: partially blocked by machine state (headless OAuth expired).

## Verified live on this machine (2026-08-03)

- `claude -p --output-format json` envelope shape recorded, including the gotcha:
  **`"subtype": "success"` coexists with `"is_error": true`** on failures. Error
  detection must use `is_error` (+ `terminal_reason`), never `subtype`. The recorded
  envelope is a regression fixture in `tests/test_llm_claude.py`.
- The headless auth failure mode is real and reproducible:
  `Failed to authenticate: OAuth session expired and could not be refreshed`, exit
  cleanly with `total_cost_usd: 0` — while the interactive session works. This is
  why `talkbrief doctor` runs a paid probe (~$0.01) before any pipeline compute.
- `--json-schema` takes INLINE JSON; a file path fails with `Unrecognized token '/'`
  (verified in a sibling project on 2.1.212).

## Pending a working auth (blocked, run before first real release)

1. `--tools Read` image ingestion end-to-end: 3 slide images, model must describe
   all 3 → proves the Read-tool image path works headless.
2. Locate the structured-output field name in a SUCCESS envelope when `--json-schema`
   is used (parser already falls back to fenced JSON in `result`).
3. `--setting-sources` isolation: confirm user hooks/CLAUDE.md are suppressed
   without breaking OAuth.
4. Wall-clock at 24 images per call.
