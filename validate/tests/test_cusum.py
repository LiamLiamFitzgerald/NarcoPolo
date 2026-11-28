"""D2 (#174): h fitted on null simulator runs meets A1's target, and detectors pick it up."""

import json

import pytest

from core import io
from core.config import load
from validate import cusum


def test_fitted_h_meets_the_quiet_cell_target_on_null_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path / "reports"))
    body = cusum.write_cusum_report(seeds=[0])
    assert body["quiet_cells"] > 0 and body["regime"] == "null"
    assert body["alarms_per_91_days"] <= 91 / body["alarm_days_target"] + 1e-9
    saved = json.loads(cusum.report_path().read_text())
    assert (
        saved["h"] == pytest.approx(body["h"]) and saved["config_hash"] == load(io.CONFIG_PATH)[1]
    )


def test_detectors_use_a_fresh_report_and_ignore_a_stale_one(tmp_path, monkeypatch):
    from detectors import _common

    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path))
    (tmp_path / "cusum_h.json").write_text(
        json.dumps({"h": 1.25, "config_hash": load(io.CONFIG_PATH)[1]})
    )
    assert _common._fitted_h() == 1.25
    (tmp_path / "cusum_h.json").write_text(json.dumps({"h": 1.25, "config_hash": "stale"}))
    assert _common._fitted_h() is None
    (tmp_path / "cusum_h.json").write_text(
        json.dumps({"h": None, "config_hash": load(io.CONFIG_PATH)[1]})
    )
    assert _common._fitted_h() is None  # target not binding: keep the configured h
