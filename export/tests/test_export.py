import json

import pytest

from export import build_snapshot, data_label, heatmap_values, scan_identities
from patrol import aircraft_plan, ship_plan


def test_data_label_comes_from_provenance():
    assert data_label(["simulated", "simulated"]) == "simulated"
    assert data_label(["real"]) == "real"
    assert data_label(["real", "simulated"]) == "mixed"
    for bad in ([], ["demo"]):
        with pytest.raises(ValueError):
            data_label(bad)


def test_scan_identities_flags_ids_but_not_iso_times_or_decimals():
    scan_identities({"t": "2026-11-23T06:00:00Z", "x": 123456789.5, "n": 12345678})
    for bad in ("id 123456789", "IMO 9074729", "call_sign"):
        with pytest.raises(ValueError):
            scan_identities({"v": bad})


def test_unobserved_cells_are_none_not_zero():
    cells = heatmap_values(None, None, None, "2026-W47")
    blind = [c for c in cells if not c["observed"]]
    assert blind and all(c[k] is None for c in blind for k in ("normal", "obs_vs_exp", "unusual"))


def test_snapshot_round_trips_with_label_and_plan(tmp_path):
    plan, out = tmp_path / "plan.json", tmp_path / "snapshot.json"
    ship_plan(out=plan)
    aircraft_plan(out=plan)
    build_snapshot(["simulated"], plan_path=plan, out=out)
    snap = json.loads(out.read_text())
    assert set(snap) == {"meta", "basemap", "cells", "sites", "piers", "plan", "validation"}
    assert snap["meta"]["data_label"] == "simulated"
    assert set(snap["cells"]) == set(snap["meta"]["weeks"])
    assert all("lon" in s for stops in snap["plan"].values() for s in stops)
