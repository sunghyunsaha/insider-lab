import json

import pytest

from insiderlab import pipeline, report
from insiderlab.config import load_config
from insiderlab.synthetic import make_world


@pytest.fixture(scope="module")
def cfg():
    return load_config("configs/base.yaml")


def _run(cfg, drift, seed=0):
    w = make_world(seed=seed, drift_daily=drift, n_tickers=80, n_insiders=300)
    return pipeline.run(
        w["tx"], w["panel"], w["bench"], w["fx"], cfg, "synthetic", log=lambda *a: None
    )


def test_finds_planted_effect_and_control_passes(cfg):
    res = _run(cfg, 0.0005)
    hyp = {h["id"]: h for h in res["hypotheses"]}
    assert hyp["H1"]["supported"] and hyp["H2"]["supported"]
    assert hyp["H5"]["t_hac"] < 2.5  # routine buyers: nothing planted, nothing strong found
    assert not hyp["H4"]["supported"]  # nothing planted for drawdowns
    assert res["sample"]["holdout"] == "locked"
    assert res["sample"]["end"] < "2024-01-01"


def test_null_world_finds_nothing(cfg):
    res = _run(cfg, 0.0, seed=3)
    conf = [h for h in res["hypotheses"] if h["kind"] != "control"]
    assert sum(h["supported"] for h in conf) <= 1  # at most a rare false positive
    assert res["diagnostics"]["dsr"] < 0.95


def test_report_renders(cfg, tmp_path):
    res = _run(cfg, 0.0005)
    pipeline.save(res, tmp_path / "results")
    readme = tmp_path / "README.md"
    readme.write_text("x\n<!-- results:start -->\nPLACEHOLDER\n<!-- results:end -->\ny\n")
    body = report.render(tmp_path / "results", tmp_path, readme)
    assert "deflated Sharpe ratio" in body and "H6" in body
    assert "PLACEHOLDER" not in readme.read_text()
    assert (tmp_path / "figures" / "cumulative_excess.png").exists()
    data = json.loads((tmp_path / "results" / "backtest.json").read_text())
    assert data["diagnostics"]["n_trials"] == 36


def test_every_cli_command_has_a_handler():
    import argparse

    from insiderlab import cli

    src = open(cli.__file__, encoding="utf-8").read()
    parser_cmds = {line.split('"')[1] for line in src.splitlines() if "sub.add_parser(" in line}
    for cmd in parser_cmds:
        assert f'"{cmd}": cmd_' in src, f"{cmd} has no handler"
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)
