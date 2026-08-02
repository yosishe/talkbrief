# Contributing

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest          # 55 tests — no network, no LLM
.venv/bin/ruff check src tests
```

## The real E2E smoke (not in CI — run locally before a release)

1. `talkbrief doctor` — everything green, including the claude -p probe.
2. `talkbrief run https://www.youtube.com/watch?v=zjkBMFhNj_g` (Karpathy, "Intro to
   Large Language Models", ~60 min, slide-dense).
3. Acceptance checklist:
   - slide count sane (±20% of a manual count over a sampled 10 minutes);
   - open `report/report.html`: pick 5 quote chips at random, click each — the
     YouTube deep link must land within a few seconds of the quoted words;
   - `verification.quotes_grounded / quotes_total ≥ 0.9`;
   - `--lang he` run renders RTL correctly (spot-check a slide card and the TOC).
4. Regenerate `examples/report-sample.html` from this run for the release.

## Test fixture

`tests/conftest.py` builds a synthetic 215 s deck with ffmpeg+numpy only (no fonts,
no network): a 95 s hold, an A→B→A return, and a jittering slide that only the union
floor can catch. If you touch the detector, `tests/test_slides.py::test_golden_fixture_detection`
is the regression gate.
