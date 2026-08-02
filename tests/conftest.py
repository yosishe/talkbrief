"""Shared fixtures. The synthetic fixture video is built with ffmpeg + numpy only —
no fonts, no network — and exercises every detector path with KNOWN timings:

    0–20    S1  static slide
   20–115   S2  static slide held 95 s
  115–125   S1  again (A→B→A return → second span)
  125–140   S4  static slide
  140–150   S5  static slide
  150–215   S6  jittering slide: consecutive frames never settle, so the hash
                detector is blind to it — only the 45 s union floor (tick at 180 s)
                can catch it. This reproduces the measured long-slide miss.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

W, H = 320, 180
FPS = 1
DURATION = 215

SEGMENTS = [  # (slide_key, start, end)
    ("s1", 0, 20),
    ("s2", 20, 115),
    ("s1", 115, 125),
    ("s4", 125, 140),
    ("s5", 140, 150),
    ("jitter", 150, 215),
]


def _pattern(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), rng.integers(30, 220, size=3), dtype=np.uint8)
    for _ in range(6):
        x0, y0 = int(rng.integers(0, W - 60)), int(rng.integers(0, H - 40))
        w, h = int(rng.integers(40, 120)), int(rng.integers(15, 60))
        img[y0 : min(H, y0 + h), x0 : min(W, x0 + w)] = rng.integers(0, 255, size=3)
    for row in range(20, H, 34):  # text-like stripes
        img[row : row + 6, 20 : W - 20] = rng.integers(0, 255, size=3)
    return img


def _frames() -> np.ndarray:
    frames = np.zeros((DURATION, H, W, 3), dtype=np.uint8)
    patterns = {k: _pattern(i + 7) for i, k in enumerate(["s1", "s2", "s4", "s5"])}
    jitter_base = _pattern(99)
    for key, start, end in SEGMENTS:
        for t in range(start, end):
            if key == "jitter":
                f = jitter_base.copy()
                # a moving bar: consecutive dhash distance stays above `stability`,
                # so no sample ever settles — the hash detector cannot see this slide
                x = (t * 40) % (W - 40)
                f[:, x : x + 40] = 255
                frames[t] = f
            else:
                frames[t] = patterns[key]
    return frames


@pytest.fixture(scope="session")
def fixture_video(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("fixture") / "video.mp4"
    frames = _frames()
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-pix_fmt", "yuv420p", str(out)],
        input=frames.tobytes(), capture_output=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-500:]
    return out


def make_captions_json3(duration: int = DURATION, step: int = 4) -> dict:
    """Deterministic caption track: one cue every `step` seconds with distinctive text."""
    events = []
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    for i, t in enumerate(range(0, duration - step, step)):
        text = (
            f"segment {i:02d} the speaker explains {words[i % len(words)]} "
            f"topic number {i:02d} in detail here"
        )
        events.append({"tStartMs": t * 1000, "dDurationMs": step * 1000,
                       "segs": [{"utf8": text}]})
    return {"events": events}


@pytest.fixture()
def run_dir(tmp_path, fixture_video):
    """A pre-populated run directory that skips the network fetch stage entirely."""
    from talkbrief.rundir import RunDir
    from talkbrief.util import write_json

    rd = RunDir(tmp_path / "abcdefghijk__fixture-talk")
    rd.ensure()
    (rd.media_dir / "video.mp4").write_bytes(fixture_video.read_bytes())
    meta = {
        "id": "abcdefghijk",
        "url": "https://youtu.be/abcdefghijk",
        "title": "Fixture Talk",
        "channel": "Fixture Channel",
        "duration_s": float(DURATION),
        "upload_date": "20260101",
        "language": "en",
        "description": "synthetic",
        "chapters": [],
        "captions": {"manual": ["en"], "auto": []},
        "caption_provenance": {"kind": "manual", "track": "en", "cue_count": None,
                               "asr_model": None},
        "media_file": "media/video.mp4",
    }
    write_json(rd.meta_path, meta)
    write_json(rd.captions_dir / "cap.en.json3", make_captions_json3())
    return rd, meta
