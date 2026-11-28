import numpy as np
import pytest

from core import io
from core.grid import _origin
from core.schemas import check_json, check_raster

STOP = {"id": "S01", "arrival_utc": "2026-11-27T12:00:00Z", "dwell_h": 1}
PLAN = {"ship": [{**STOP, "id": "base", "dwell_h": 0}, STOP], "aircraft": [STOP]}
SNAP = {
    "meta": {"data_label": "simulated"},
    "basemap": {},
    "cells": {},
    "sites": [],
    "piers": [],
    "plan": PLAN,
    "validation": {},
}


def test_rasters():
    ok = np.zeros((4, 4), np.uint8)
    check_raster("reference/sea_250m", ok, pixel_m=250)
    check_raster("reference/land_mask_10m", ok, pixel_m=10, origin=_origin())
    for bad, kw in [
        (ok.astype(np.int16), {"pixel_m": 250}),
        (ok + 2, {"pixel_m": 250}),
        (ok, {"pixel_m": 10}),  # sea raster is 250 m
        (ok[0], {"pixel_m": 250}),
    ]:
        with pytest.raises(ValueError):
            check_raster("reference/sea_250m", bad, **kw)
    with pytest.raises(ValueError, match="origin"):
        check_raster("reference/static_mask_10m", ok, pixel_m=10, origin=(1.0, 2.0))


def test_plan_and_snapshot_checks():
    check_json("patrol/plan", PLAN)
    check_json("export/snapshot", SNAP)
    for bad in [
        {},
        {"boat": [STOP]},
        {"ship": [{**STOP, "arrival_utc": "2026-11-27 12:00"}]},
        {"ship": [{**STOP, "dwell_h": -1}]},
        {"ship": [{"id": 3, "arrival_utc": "2026-11-27T12:00:00Z", "dwell_h": 0}]},
    ]:
        with pytest.raises(ValueError):
            check_json("patrol/plan", bad)
    with pytest.raises(ValueError, match="data_label"):
        check_json("export/snapshot", {**SNAP, "meta": {"data_label": "fake"}})
    with pytest.raises(ValueError, match="keys"):
        check_json("export/snapshot", {k: v for k, v in SNAP.items() if k != "plan"})


def test_json_stage_round_trip_and_staleness(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)
    path = io.write_json_stage("patrol/plan", PLAN, "simulated")
    assert path.name == "plan.json" and io.read_json_stage("patrol/plan") == PLAN
    cfg.write_text(cfg.read_text().replace("x0: 380000", "x0: 390000"))
    with pytest.raises(ValueError, match="stale"):
        io.read_json_stage("patrol/plan")
    with pytest.raises(ValueError):
        io.write_json_stage("patrol/plan", {"ship": [{**STOP, "dwell_h": -1}]}, "real")


def test_bandit_fields_and_state():
    check_json("patrol/plan", {"ship": [{**STOP, "theta": 0.3, "reason": "explore"}]})
    for bad in [{"ship": [{**STOP, "theta": 2}]}, {"ship": [{**STOP, "reason": "guess"}]}]:
        with pytest.raises(ValueError):
            check_json("patrol/plan", bad)
    check_json("patrol/bandit_state", {"s1": {"alpha": 1.5, "beta": 4.0, "last_visit_week": None}})
    with pytest.raises(ValueError):
        check_json("patrol/bandit_state", {"s1": {"alpha": 0, "beta": 1, "last_visit_week": 3}})
