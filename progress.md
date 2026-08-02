# progress.md — talkbrief (state mirror; continuously overwritten)

Statuses: `DONE` (only with proof: path + passing test / real run output) · `PARTIAL` ·
`NOT STARTED` · `DIVERGED` (also gets a decisions.md entry).

Last update: 2026-08-03 (scaffold session).

| Component | Status | Proof / note |
|---|---|---|
| Repo scaffold (pyproject, LICENSE, CI, git) | PARTIAL | files written, first commit pending |
| config + schemas + rundir/manifest | NOT STARTED | |
| fetch stage (yt-dlp, captions, provenance) | NOT STARTED | |
| slides stage (detector union, OCR ladder, collapse) | NOT STARTED | |
| transcript stage (json3 flatten, coverage, ASR extra) | NOT STARTED | |
| align stage (windows, primary/context) | NOT STARTED | |
| LLM backends (claude_code, fake, api stub) | NOT STARTED | |
| synthesize (map/reduce, routing) | NOT STARTED | |
| verify (quote anchoring, coverage recall) | NOT STARTED | |
| render (HTML report, RTL, PDF extra) | NOT STARTED | |
| CLI (run/batch/resume/render/doctor) | NOT STARTED | |
| test suite (synthetic fixture, golden, units) | NOT STARTED | |
| real E2E demo + examples/report-sample.html | NOT STARTED | BLOCKED: `claude -p` OAuth broken on this machine (measured 2026-08-03); Yosi must run `claude auth login` / `claude setup-token` |
| README (hero, positioning, quickstart) | NOT STARTED | |
| Public publish (GitHub + PyPI) | NOT STARTED | Yosi's click via SHIP-QUEUE; never autonomous |
