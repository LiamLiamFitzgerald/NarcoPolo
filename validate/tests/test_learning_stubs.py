import json

import pytest

from core.config import load
from core.io import CONFIG_PATH
from validate.signals import AGENTS, BACKTEST_COLUMNS, backtest_agent, overlap, write_signals_report
from validate.train import fit_site_model, model_path


def test_signals_interface(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path))
    assert list(backtest_agent("gi", "fixed", [1]).columns) == BACKTEST_COLUMNS
    with pytest.raises(ValueError):
        backtest_agent("nope", "fixed", [1])
    k = overlap([1])
    assert (k.to_numpy().diagonal() == 1).all() and list(k.index) == list(AGENTS)
    merged = json.loads(write_signals_report([1]).read_text())["merged"]
    assert sorted(a for g in merged for a in g) == sorted(
        load(CONFIG_PATH)[0]["learn"]["agents"]
    )  # a partition


def test_model_file_matches_what_fuse_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    m = fit_site_model(["fixed"], [1, 2])
    on_disk = json.loads(model_path().read_text())
    assert on_disk == m and m["rung"] == 0
    assert set(m) == {
        "rung",
        "features",
        "weights",
        "intercept",
        "config_hash",
        "metrics",
        "seeds",
        "regimes",
    }
    assert m["config_hash"] == load(CONFIG_PATH)[1]
