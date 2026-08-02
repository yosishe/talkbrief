import pytest

from talkbrief.cli import _cfg_from, build_parser


def test_run_defaults():
    args = build_parser().parse_args(["run", "https://youtu.be/abc"])
    cfg = _cfg_from(args)
    assert cfg.lang == "en" and cfg.interval == 2.0 and cfg.floor_seconds == 45.0
    assert cfg.backend == "claude-code"


def test_flags_map_to_config():
    args = build_parser().parse_args([
        "run", "u", "--lang", "he", "--pdf", "--interval", "1.5",
        "--only", "slides,align", "--force", "render", "--embed", "never",
    ])
    cfg = _cfg_from(args)
    assert cfg.lang == "he" and cfg.pdf is True and cfg.interval == 1.5
    assert cfg.only_stages == ("slides", "align")
    assert cfg.force_stages == ("render",)
    assert cfg.embed == "never"


def test_unknown_stage_rejected():
    args = build_parser().parse_args(["run", "u", "--only", "nonsense"])
    with pytest.raises(SystemExit):
        _cfg_from(args)


def test_doctor_subcommand_parses():
    args = build_parser().parse_args(["doctor", "--no-probe"])
    assert args.no_probe is True


def test_render_missing_artifacts_fails_cleanly(tmp_path, capsys):
    from talkbrief.cli import cmd_render

    args = build_parser().parse_args(["render", str(tmp_path)])
    assert cmd_render(args) == 1
    assert "run the pipeline first" in capsys.readouterr().err
