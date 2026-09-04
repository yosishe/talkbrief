# decisions.md — talkbrief

Append-only. Every decision, spec change, and abandoned approach, with the **why**.
`spec = should-be` · `progress.md = is` · `decisions.md = why`. Never mix them.

---

## D-001 — talkbrief is the THIRD declared sibling in the video→slides family

**2026-08-03.** Twin-check found two existing relatives, and this project exists only because
its product is different from both:

- `~/.claude/skills/video-digest/` — personal Hebrew prose digest skill, in daily use. Stays
  canonical for "video → Hebrew digest for Yosi".
- `~/Workspace/lecturedeck/` — production deck-reconstruction system. Stays canonical for
  "video → faithful reconstructed deck + PPTX/records".
- **talkbrief** — public, English-first, MIT: "talk → grounded per-slide notes + global
  narrative + interactive single-file HTML report", riding the local Claude Code CLI.

Clean-room code. What crosses over is the *measured findings only* (union detector recall
84.6%→92.3%, no motion masks, image-routing 24× token cut, `is_error`+`subtype:"success"`
envelope gotcha, `-copyts`, caption provenance). Vault-side record: central D-141.

## D-002 — Named `talkbrief` because `slidegeist` is taken by a real competitor

**2026-08-03.** The planned name `slidegeist` exists on PyPI (itpplasma, v2026.4.23):
slide extraction via global pixel difference + Whisper-server transcription + tesseract OCR +
markdown export + AI descriptions via a local llama.cpp server. It requires two running local
inference servers and stops short of grounded synthesis, verification, and a report.
`talkbrief` was verified free (PyPI 404) before adoption. The competitor is listed in the
README positioning table — it is honest prior art, not a rival to hide.

## D-003 — v1 LLM backend is the local Claude Code CLI only, behind a seam

**2026-08-03.** Yosi's explicit product choice: no API-key handling in v1; the tool rides the
already-authenticated `claude` CLI (`claude -p`, headless). Consequences accepted: the
audience is Claude Code users, and a broken headless OAuth (measured live on this machine
2026-08-02 and 2026-08-03: `Failed to authenticate: OAuth session expired`) is a hard
prerequisite surfaced by `talkbrief doctor`, not a code path we can fix. The
`LLMBackend` ABC + registry exists so v2 adds an Anthropic-API backend without refactoring;
`AnthropicAPIBackend` ships as a documented stub, `FakeBackend` serves tests.

## D-004 — argparse over typer/click

**2026-08-03.** The runtime dependency list is a selling point of a local-first tool, the CLI
surface is small and stable, and the beauty budget goes into the HTML report, not the
terminal. Zero-dep argparse it is.

## D-005 — First real run findings (Karpathy, 2026-08-03)

**2026-08-03.** `--only fetch,slides,transcript,align` on zjkBMFhNj_g (59.8 min):
46 slides kept (51 hash + 0 floor; 5 build-collapsed once Apple Vision OCR replaced
tesseract — the collapse pass needs decent OCR to see containment), 1,704 caption
segments at 100% coverage, 21 windows following the video's own chapters. Full
fake-backend render: 8.0 MB single file — inside the predicted 5–9 MB envelope.

Two decisions from what the run showed:
1. **Span labels cap at 3 (+N).** A near-blank "Demo" slide legitimately collects 13
   return-spans (blank frames match each other); the data stays complete in
   slides.json, only the display truncates. No "smart" blank-frame filtering — that
   is the motion-mask class of cleverness this project explicitly avoids.
2. **Visual QA path = headless Chrome screenshots**, not the IDE browser pane: the
   pane mis-captures after programmatic scroll on the 8 MB page (page geometry
   verified healthy via DOM measurements). Recorded so nobody "fixes" the CSS for a
   capture artifact.

<!-- APPEND BELOW — do not delete this line -->
