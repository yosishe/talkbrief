# progress.md — talkbrief (state mirror; continuously overwritten)

Statuses: `DONE` (only with proof: path + passing test / real run output) · `PARTIAL` ·
`NOT STARTED` · `DIVERGED` (also gets a decisions.md entry).

Last update: 2026-08-03 ~02:35 (build session, day 1).

| Component | Status | Proof |
|---|---|---|
| Repo scaffold (pyproject, LICENSE, CI, git) | DONE | commit `ff1bf3a`; `pip install -e ".[dev]"` succeeds |
| config + schemas + rundir/manifest (+ downstream invalidation) | DONE | `tests/test_rundir.py`, `tests/test_schemas.py` — in the 55/55 green run |
| fetch stage (yt-dlp, captions, provenance) | DONE | real run: Karpathy zjkBMFhNj_g fetched ≤720p, auto captions json3, `talkbrief-runs/zjkBMFhNj_g__*/meta.json` |
| slides stage (union detector, OCR ladder, collapse) | DONE | golden fixture test green; real run: **46 slides** (51 hash + 0 floor, 5 build-collapsed with Apple Vision OCR) |
| transcript stage | DONE | real run: 1704 segments, provenance `auto`, 100% coverage; `tests/test_transcript.py` |
| align stage | DONE | real run: 21 windows following the video's chapters, 46 slides assigned; `tests/test_align.py` |
| LLM backends (claude_code, fake, api stub) | DONE (code) | `tests/test_llm_claude.py` incl. recorded `is_error`+`subtype:"success"` envelope; **claude-code NOT yet exercised live — OAuth broken on this machine** |
| synthesize (map/reduce, routing) | DONE (offline) | full pipeline with FakeBackend on fixture + real run dir; real-model run pending auth |
| verify (quote anchoring, coverage recall) | DONE | `tests/test_verify.py` (digit-exact fuzzy, ellipsis, slide fallback); fake e2e: 46/46 grounded |
| render (HTML report, RTL, PDF extra) | DONE (HTML) | 8.0 MB single-file report of the real talk; headless-Chrome screenshots (desktop+mobile) verified; he-RTL asserted in tests; **PDF extra not yet run** (weasyprint not installed locally) |
| CLI (run/batch/resume/render/doctor) | DONE (code) | used for all real runs above; batch/resume covered by unit tests only |
| test suite | DONE | **55/55 passing**, no network, no LLM; ruff clean |
| real E2E with Claude synthesis + examples/report-sample.html | **BLOCKED** | `claude -p` OAuth expired (measured live 2026-08-03, twice); Yosi must run `claude auth login` / `claude setup-token`; after that: `talkbrief run <url> --force synthesize` re-runs synthesize→verify→render automatically |
| README | DONE (v1 text) | hero screenshot pending real-content report |
| Public publish (GitHub + PyPI) | NOT STARTED | Yosi's click via SHIP-QUEUE after critic gate; never autonomous |

Known observations (not blockers):
- A near-blank "Demo" slide in the Karpathy run collects 13 return-spans (blank frames
  match each other); display now caps span labels at 3 (+N). Detection unaffected.
- The Claude-Code browser pane mis-captures screenshots after programmatic scroll on
  the 8 MB report; page geometry verified healthy via DOM, and headless Chrome
  screenshots are the reliable QA path.
