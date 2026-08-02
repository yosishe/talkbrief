"""Slide detection: a UNION of two detectors, because no single one survives real video.

Measured background (from a prior private pipeline, findings carried forward):

- A perceptual-hash-only detector is INVERTED on composited conference video: the same
  slide at two moments measured 0.20 apart while two different slides measured 0.06 —
  at every grid size from 16×16 to 96×96. No threshold separates them.
- A fixed-interval floor is the only detector that cannot miss a long-held slide
  (a 184-second architecture slide was lost without it). The union of both detectors
  raised recall from 84.6% to 92.3% against a hand-built gold set.
- Motion masks are a trap on screencasts: one looked like a 59% saving and destroyed
  64 distinct code headlines. There is deliberately no motion mask here.

Downstream OCR-text dedup keeps the floor cheap: recall first, precision second.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import RunConfig
from .ocr import read_image
from .rundir import RunDir
from .schemas import validate
from .util import hms, run_cmd, write_json

log = logging.getLogger("talkbrief")

GRID = 32  # cheap-pass thumbnail edge; hash is 32×31 = 992 bits


def probe_duration(video: Path) -> float:
    res = run_cmd(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        timeout=60,
    )
    try:
        return float(res.stdout.strip())
    except ValueError as e:
        raise RuntimeError(f"ffprobe could not read duration of {video}") from e


def sample_frames(video: Path, interval: float) -> np.ndarray:
    """One ffmpeg decode: grayscale GRID×GRID thumbnails every `interval` seconds."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps=1/{interval},scale={GRID}:{GRID}",
        "-pix_fmt", "gray",
        "-f", "rawvideo", "-",
    ]
    log.debug("exec: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg sampling failed: {proc.stderr[-500:].decode(errors='replace')}")
    n = len(proc.stdout) // (GRID * GRID)
    return np.frombuffer(proc.stdout[: n * GRID * GRID], dtype=np.uint8).reshape(n, GRID, GRID)


def dhash_bits(frames: np.ndarray) -> np.ndarray:
    """Horizontal difference hash, pure numpy: (N, GRID, GRID-1) bool."""
    return frames[:, :, 1:] > frames[:, :, :-1]


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(a ^ b))


def _dist_many(one: np.ndarray, many: list[np.ndarray]) -> np.ndarray:
    return np.array([_dist(one, m) for m in many]) if many else np.empty(0)


@dataclass
class Candidate:
    rep_i: int  # representative sample index
    spans: list[list[int]] = field(default_factory=list)  # inclusive sample-index spans
    source: str = "hash"
    bits: np.ndarray | None = None

    def covered(self, i: int) -> bool:
        return any(s <= i <= e for s, e in self.spans)

    def total_samples(self) -> int:
        return sum(e - s + 1 for s, e in self.spans)


def pick_keyframes(
    bits: np.ndarray, threshold: float, stability: float
) -> list[Candidate]:
    """Stability-segmentation detector.

    A frame is *settled* iff its distance to the NEXT sample ≤ `stability` — this
    rejects mid-fades and gesturing speakers. A settled frame is *new* iff its distance
    to EVERY kept candidate > `threshold`; comparing against all kept slides (not just
    the previous one) is what absorbs director cuts slide→speaker→same slide.
    """
    kept: list[Candidate] = []
    n = len(bits)
    for i in range(n - 1):
        if _dist(bits[i], bits[i + 1]) > stability:
            continue  # transition or motion; not a slide moment
        dists = _dist_many(bits[i], [c.bits for c in kept])
        j = int(dists.argmin()) if dists.size else -1
        if dists.size and dists[j] <= threshold:
            spans = kept[j].spans
            if spans and i <= spans[-1][1] + 1:
                spans[-1][1] = i  # contiguous: still displayed, not "returning"
            else:
                spans.append([i, i])
        else:
            kept.append(Candidate(rep_i=i, spans=[[i, i]], bits=bits[i]))
    return kept


def union_floor(
    kept: list[Candidate], bits: np.ndarray, interval: float,
    floor_seconds: float, stability: float,
) -> list[Candidate]:
    """Force a candidate at every floor tick not covered by the hash detector.

    The floor has no similarity metric to fool. A floor candidate is merged into an
    existing candidate only when nearly IDENTICAL (≤ stability); anything looser would
    reimport the inverted-metric failure the floor exists to bypass. Remaining
    duplicates are cleaned by OCR-text dedup downstream.
    """
    if floor_seconds <= 0:
        return kept
    n = len(bits)
    out = list(kept)
    tick = floor_seconds
    while tick < n * interval:
        i = int(round(tick / interval))
        tick += floor_seconds
        if i >= n or any(c.covered(i) for c in out):
            continue
        # take the most-settled sample near the tick to avoid grabbing a transition
        lo, hi = max(0, i - 2), min(n - 1, i + 2)
        cand_i = min(
            range(lo, hi + 1),
            key=lambda k: _dist(bits[k], bits[min(k + 1, n - 1)]),
        )
        dists = _dist_many(bits[cand_i], [c.bits for c in out])
        if dists.size and float(dists.min()) <= stability:
            j = int(dists.argmin())
            out[j].spans.append([cand_i, cand_i])
            out[j].spans.sort()
            continue
        out.append(Candidate(rep_i=cand_i, spans=[[cand_i, cand_i]], source="floor", bits=bits[cand_i]))
    return out


def extract_full(video: Path, t: float, dest: Path) -> None:
    """Full-res re-extract of one frame. Media is fetched at ≤720p on purpose —
    1080p measured ~2.8× the bytes for no OCR gain on slide text."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(dest)],
        timeout=120, check=True,
    )


def _tokens(text: str) -> set[str]:
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(w) >= 2}


def collapse_builds(slides: list[dict], containment: float = 0.90, jaccard: float = 0.92) -> list[dict]:
    """Collapse progressive-build slides into the FINAL build, and drop text-duplicates.

    A slide whose tokens are ≥`containment` contained in the NEXT slide's tokens (and
    that leads into it within a short gap) is a build step: keep the final frame, give
    it the union of spans and the earliest first_seen. This deliberately keeps the
    *last* frame of a build sequence — the fullest one.
    """
    slides = sorted(slides, key=lambda s: s["first_seen_s"])

    def merge(dst: dict, src: dict, as_build: bool) -> None:
        dst["on_screen"] = sorted(
            dst["on_screen"] + src["on_screen"], key=lambda sp: sp["start_s"]
        )
        dst["first_seen_s"] = min(dst["first_seen_s"], src["first_seen_s"])
        dst["hms"] = hms(dst["first_seen_s"])
        if as_build:
            dst["builds_collapsed"] += 1 + src["builds_collapsed"]

    changed = True
    while changed:
        changed = False
        for i in range(len(slides) - 1):
            a, b = slides[i], slides[i + 1]
            ta, tb = _tokens(a["ocr_text"]), _tokens(b["ocr_text"])
            if len(ta) < 3 or not tb:
                continue
            gap = b["on_screen"][0]["start_s"] - a["on_screen"][-1]["end_s"]
            if gap > 15:
                continue
            if len(ta & tb) / len(ta) >= containment and len(tb) >= len(ta):
                merge(b, a, as_build=True)
                slides.pop(i)
                changed = True
                break

    # floor-introduced duplicates: same text elsewhere in the deck
    out: list[dict] = []
    for s in slides:
        ts = _tokens(s["ocr_text"])
        dup = None
        if len(ts) >= 3:
            for kept in out:
                tk = _tokens(kept["ocr_text"])
                if tk and len(ts & tk) / len(ts | tk) >= jaccard:
                    dup = kept
                    break
        if dup is not None:
            merge(dup, s, as_build=False)
        else:
            out.append(s)

    for s in out:
        spans = [sp for sp in s["on_screen"]]
        # fuse overlapping/adjacent spans after merges
        fused: list[dict] = []
        for sp in spans:
            if fused and sp["start_s"] <= fused[-1]["end_s"] + 0.001:
                fused[-1]["end_s"] = max(fused[-1]["end_s"], sp["end_s"])
            else:
                fused.append(dict(sp))
        s["on_screen"] = fused
        s["on_screen_total_s"] = round(sum(sp["end_s"] - sp["start_s"] for sp in fused), 3)
        s["times_returned"] = max(0, len(fused) - 1)
    return out


def run_slides(rd: RunDir, meta: dict, cfg: RunConfig) -> dict:
    video = rd.root / meta["media_file"]
    frames = sample_frames(video, cfg.interval)
    if len(frames) == 0:
        raise RuntimeError(f"no frames sampled from {video}")
    bits = dhash_bits(frames)

    kept = pick_keyframes(bits, cfg.threshold, cfg.stability)
    n_hash = len(kept)
    kept = union_floor(kept, bits, cfg.interval, cfg.floor_seconds, cfg.stability)
    n_floor = len(kept) - n_hash

    if len(kept) > cfg.max_slides:
        kept.sort(key=lambda c: c.total_samples(), reverse=True)
        dropped = len(kept) - cfg.max_slides
        kept = kept[: cfg.max_slides]
        log.warning("slides: capped at %d, dropped %d smallest candidates", cfg.max_slides, dropped)

    kept.sort(key=lambda c: c.spans[0][0])

    engines_used: dict[str, int] = {}
    vision_available = False
    raw_slides: list[dict] = []
    for idx, cand in enumerate(kept, start=1):
        longest = max(cand.spans, key=lambda sp: sp[1] - sp[0])
        rep_t = (longest[0] + longest[1]) / 2 * cfg.interval + cfg.interval / 2
        file = rd.slides_dir / f"slide_{idx:03d}.jpg"
        extract_full(video, rep_t, file)
        ocr = read_image(file)
        engines_used[ocr.engine] = engines_used.get(ocr.engine, 0) + 1
        vision_available = vision_available or ocr.vision_available
        first_seen = cand.spans[0][0] * cfg.interval
        raw_slides.append({
            "id": f"s{idx:03d}",
            "index": idx,
            "file": file.name,
            "first_seen_s": round(first_seen, 3),
            "hms": hms(first_seen),
            "on_screen": [
                {"start_s": round(s * cfg.interval, 3),
                 "end_s": round((e + 1) * cfg.interval, 3)}
                for s, e in cand.spans
            ],
            "on_screen_total_s": 0.0,  # filled by collapse pass
            "times_returned": 0,
            "ocr_text": ocr.text,
            "ocr_chars": len(ocr.text),
            "ocr_engine": ocr.engine,
            "builds_collapsed": 0,
            "source": cand.source,
        })

    final = collapse_builds(raw_slides)

    # renumber sequentially; remove images of merged candidates (derived artifacts)
    keep_files = {s["file"] for s in final}
    for p in rd.slides_dir.glob("slide_*.jpg"):
        if p.name not in keep_files:
            p.unlink()
    final.sort(key=lambda s: s["first_seen_s"])
    for new_idx, s in enumerate(final, start=1):
        new_name = f"slide_{new_idx:03d}.jpg"
        if s["file"] != new_name:
            (rd.slides_dir / s["file"]).rename(rd.slides_dir / new_name)
            s["file"] = new_name
        s["id"] = f"s{new_idx:03d}"
        s["index"] = new_idx

    doc = {
        "schema_version": 1,
        "params": cfg.stage_params("slides"),
        "ocr": {"engines_used": engines_used, "vision_available": vision_available},
        "slides": final,
        "stats": {
            "frames_sampled": int(len(frames)),
            "candidates_hash": n_hash,
            "candidates_floor": n_floor,
            "kept": len(final),
            "collapsed_or_deduped": len(raw_slides) - len(final),
        },
    }
    validate("slides", doc)
    write_json(rd.slides_json, doc)
    log.info(
        "slides: %d kept (%d hash + %d floor, %d collapsed/deduped)",
        len(final), n_hash, n_floor, len(raw_slides) - len(final),
    )
    return doc
