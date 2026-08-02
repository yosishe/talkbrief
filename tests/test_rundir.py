from talkbrief.config import RunConfig
from talkbrief.rundir import RunDir


def _init(tmp_path, cfg):
    rd = RunDir.create(tmp_path, "abc12345678", "Some Talk Title")
    rd.ensure()
    rd.init_manifest("https://youtu.be/abc12345678", "abc12345678", cfg, {"ffmpeg": "7.1"})
    return rd


def test_done_stage_with_same_params_is_skipped(tmp_path):
    cfg = RunConfig(outdir=tmp_path)
    rd = _init(tmp_path, cfg)
    assert rd.should_run("slides", cfg) is True
    rd.mark("slides", "done", seconds=1.0, config_hash=cfg.stage_hash("slides"))
    assert rd.should_run("slides", cfg) is False


def test_changed_param_reruns_only_that_stage(tmp_path):
    cfg = RunConfig(outdir=tmp_path)
    rd = _init(tmp_path, cfg)
    rd.mark("fetch", "done", config_hash=cfg.stage_hash("fetch"))
    rd.mark("slides", "done", config_hash=cfg.stage_hash("slides"))
    changed = RunConfig(outdir=tmp_path, threshold=0.06)
    assert changed.stage_hash("slides") != cfg.stage_hash("slides")
    assert rd.should_run("slides", changed) is True
    assert rd.should_run("fetch", changed) is False


def test_force_overrides_done(tmp_path):
    cfg = RunConfig(outdir=tmp_path, force_stages=("slides",))
    rd = _init(tmp_path, cfg)
    rd.mark("slides", "done", config_hash=cfg.stage_hash("slides"))
    assert rd.should_run("slides", cfg) is True


def test_failed_stage_reruns(tmp_path):
    cfg = RunConfig(outdir=tmp_path)
    rd = _init(tmp_path, cfg)
    rd.mark("slides", "failed", error="boom")
    assert rd.should_run("slides", cfg) is True


def test_rerun_invalidates_downstream(tmp_path):
    cfg = RunConfig(outdir=tmp_path)
    rd = _init(tmp_path, cfg)
    for stage in ("slides", "transcript", "align", "synthesize"):
        rd.mark(stage, "done", config_hash=cfg.stage_hash(stage))
    rd.invalidate_downstream("slides")
    assert rd.should_run("slides", cfg) is False   # the stage itself stays done
    assert rd.should_run("transcript", cfg) is True
    assert rd.should_run("align", cfg) is True
    assert rd.should_run("synthesize", cfg) is True


def test_slug_in_dirname(tmp_path):
    rd = RunDir.create(tmp_path, "abc12345678", "Hebrew כותרת // Weird*Chars")
    assert rd.root.name.startswith("abc12345678__")
    assert "*" not in rd.root.name and "/" not in rd.root.name.replace(str(tmp_path), "")
