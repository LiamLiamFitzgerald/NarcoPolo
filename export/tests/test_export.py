import json
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from core import io
from core.config import load
from core.crs import to_utm
from core.schemas import check_json
from export import (
    _legends,
    _provenance,
    _weeks,
    basemap,
    build_snapshot,
    data_label,
    heatmap_values,
    scan_identities,
)
from sim.simulate import simulate

WEEK = "2026-W48"  # Monday 2026-11-23 to Sunday 2026-11-29


def _t(day: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} 10:00", tz=UTC)


def test_data_label_comes_from_provenance():
    assert data_label(["simulated", "simulated"]) == "simulated"
    assert data_label(["real"]) == "real"
    assert data_label(["real", "simulated"]) == "mixed"
    for bad in ([], ["demo"]):
        with pytest.raises(ValueError):
            data_label(bad)


def test_scan_identities_ignores_hex_hashes_that_end_in_nine_digits():
    # a config hash is 64 hex characters; about 1 in 70 end in 9 digits, which is not an MMSI
    h = "3fa9c1d0e7b24a5f8c6d1e0b9a7f3c2d4e5f60718293a4b5c6d7e8f9" + "a" + "123456789"
    scan_identities({"meta": {"config_hash": h}, "k": "x" + h})
    for bad in (
        "id 123456789",
        "123456789",
        "mmsi=123456789",
    ):  # a real stand-alone number still fails
        with pytest.raises(ValueError):
            scan_identities({"v": bad})


def test_scan_identities_flags_ids_but_not_iso_times_or_decimals():
    scan_identities({"t": "2026-11-23T06:00:00Z", "x": 123456789.5, "n": 12345678})
    for bad in ("id 123456789", "IMO 9074729", "call_sign", "mmsi", "ship_key"):
        with pytest.raises(ValueError):
            scan_identities({"v": bad})


def test_weeks_are_the_week_of_T_and_the_three_before():
    assert _weeks(date(2026, 11, 27)) == ["2026-W45", "2026-W46", "2026-W47", "2026-W48"]


def test_heatmap_values_recover_a_hand_computed_answer():
    # Cell A: 0.5 + 0.25 exposure on Monday, 0.5 on Tuesday. mu 0.2 and 0.05.
    #   normal = mean(0.2 / 0.75, 0.05 / 0.5) = mean(0.2667, 0.1) = 0.18333; exposure = 1.25
    # Cell B: a pass with zero exposure, so unobserved. Cell C: exposure only the week before.
    # Cell D: slowdown rows but no small-boat exposure this week.
    ex = pd.DataFrame(
        {
            "cell_id": ["A", "A", "A", "B", "C", "D"],
            "time_utc": [_t("2026-11-23"), _t("2026-11-23"), _t("2026-11-24")]
            + [_t("2026-11-25"), _t("2026-11-16"), _t("2026-11-16")],
            "exposure_small": [0.5, 0.25, 0.5, 0.0, 0.9, 0.0],
        }
    )
    exp = pd.DataFrame(
        {
            "cell_id": ["A", "A", "A", "B"],
            "date": [
                date(2026, 11, 23),
                date(2026, 11, 24),
                date(2026, 11, 24),
                date(2026, 11, 25),
            ],
            "event_type": ["dark_small", "dark_small", "slowdown", "dark_small"],
            "mu": [0.2, 0.05, 9.0, 0.0],
        }
    )
    fz = pd.DataFrame(
        {
            "cell_id": ["A", "A", "A", "D"],
            "date": [
                date(2026, 11, 23),
                date(2026, 11, 24),
                date(2026, 11, 16),
                date(2026, 11, 26),
            ],
            "event_type": ["slowdown", "dark_small", "dark_small", "slowdown"],
            "U": [0.4, 0.9, 0.99, 0.7],
            "agreement": [1, 3, 4, 2],
        }
    )
    got = {c["cell_id"]: c for c in heatmap_values(exp, fz, ex, WEEK)}
    assert set(got) == {"A", "B", "C", "D"}
    a = got["A"]
    assert a["observed"] and a["exposure"] == 1.25
    assert a["normal"] == pytest.approx(0.1833, abs=1e-4)
    assert a["unusual"] == 0.9  # weekly max over both event types; last week's 0.99 is ignored
    assert a["agreement"] == 3  # the badge of the row that gave the weekly max, not last week's 4
    assert got["D"]["agreement"] == 2 and got["B"]["agreement"] is None
    for c in ("B", "C", "D"):  # unobserved: never a zero in the value fields (principle 4)
        assert not got[c]["observed"] and got[c]["normal"] is None and got[c]["exposure"] == 0.0
    assert got["B"]["unusual"] is None and got["D"]["unusual"] == 0.7
    assert all(c["obs_vs_exp"] is None for c in got.values())  # needs y in fuse/cells (issue 87)


def test_basemap_simplifies_in_metres_and_returns_wgs84():
    x, y = to_utm(-9.0, 51.5)
    x, y = float(x), float(y)
    # a 10 km square with a 10 m wobble (inside 50 m tolerance) and a 400 m bump (outside it)
    ring = [(x, y), (x + 5000, y + 10), (x + 10000, y), (x + 10000, y + 10000),
            (x + 5000, y + 10400), (x, y + 10000)]  # fmt: skip
    fc = basemap(Polygon(ring))
    coords = fc["features"][0]["geometry"]["coordinates"][0]
    assert len(coords) == 6  # 5 distinct vertices (wobble dropped), ring closed
    lon, lat = coords[0]
    assert abs(lon + 9.0) < 1e-4 and abs(lat - 51.5) < 1e-4


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("w")
    mp.setenv("NARCO_DATA", str(root / "data"))
    mp.setenv("NARCO_REPORTS", str(root / "reports"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    sites = io.read_stage("fuse/sites")
    s = sites.iloc[0]
    stop = lambda i, t, x, y: {"id": i, "arrival_utc": t, "dwell_h": 1.0, "x_m": x, "y_m": y}
    plan = {  # what patrol writes
        "ship": [stop("base", "2026-11-27T06:00:00Z", s.x_m - 9000, s.y_m),
                 {**stop(s.site_id, "2026-11-27T08:00:00Z", s.x_m, s.y_m), "exploration": True},
                 stop("base", "2026-11-27T10:00:00Z", s.x_m - 9000, s.y_m)],
        "aircraft": [],
    }  # fmt: skip
    io.write_json_stage("patrol/plan", plan, "simulated")
    (root / "reports").mkdir()
    (root / "reports" / "validation.json").write_text(json.dumps({"brier": 0.1, "recall": []}))
    yield root, build_snapshot()
    mp.undo()


def test_provenance_comes_from_the_stage_file_stamps(world):
    assert {_provenance(n) for n in ("fuse/sites", "reference/cells")} == {"simulated"}


def test_snapshot_has_the_spec_keys_and_a_data_driven_label(world):
    _, snap = world
    assert set(snap) == {
        "meta",
        "basemap",
        "cells",
        "sites",
        "piers",
        "plan",
        "validation",
    }
    assert snap["meta"]["data_label"] == "simulated"  # from the stamps, not typed in
    assert snap["meta"]["weeks"] == ["2026-W45", "2026-W46", "2026-W47", "2026-W48"]
    assert snap["meta"]["T"] == "2026-11-27"
    assert snap["validation"]["brier"] == 0.1


def test_snapshot_is_written_to_the_data_root_and_is_small(world):
    root, snap = world
    path = root / "data" / "export" / "snapshot.json"
    assert json.loads(path.read_text()) == json.loads(json.dumps(snap))  # tuples become lists
    assert path.stat().st_size < 5_000_000
    scan_identities(snap)
    check_json("export/snapshot", json.loads(path.read_text()))  # the contract check
    assert io.read_json_stage("export/snapshot") == json.loads(path.read_text())  # and the stamp
    check_json("patrol/plan", io.read_json_stage("patrol/plan"))


def test_snapshot_cells_are_per_week_and_unobserved_cells_are_not_zero(world):
    _, snap = world
    geom, weeks = snap["cells"]["geometry"], snap["cells"]["weeks"]
    assert set(weeks) == set(snap["meta"]["weeks"])
    for rows in weeks.values():
        assert {r["cell_id"] for r in rows} <= set(geom)
        for r in rows:
            if not r["observed"]:
                assert r["normal"] is None and r["exposure"] == 0.0
    assert any(not r["observed"] for rows in weeks.values() for r in rows)  # sim has blind spots


def test_snapshot_positions_lie_in_the_region_and_plan_stops_have_positions(world):
    _, snap = world
    r = snap["meta"]["region"]
    inside = lambda p: (
        r["lon_min"] <= p["lon"] <= r["lon_max"] and r["lat_min"] <= p["lat"] <= r["lat_max"]
    )
    assert snap["sites"] and all(inside(s) for s in snap["sites"])
    assert all(inside(p) for p in snap["piers"])
    assert all(inside(s) for s in snap["plan"]["ship"])
    assert [s.get("exploration", False) for s in snap["plan"]["ship"]] == [False, True, False]
    assert all(p["P_j"] is None for p in snap["piers"])  # not available yet (issue 88)


def test_snapshot_sites_match_the_stage_file(world):
    _, snap = world
    sites = io.read_stage("fuse/sites")
    score = dict(zip(sites["site_id"], sites["S"], strict=True))
    assert [s["id"] for s in snap["sites"]] == sorted(score, key=lambda i: -score[i])
    assert all(len(s["top_piers"]) <= 3 and isinstance(s["reasons"], list) for s in snap["sites"])
    assert np.isfinite([s["S"] for s in snap["sites"]]).all()
    assert datetime.fromisoformat(snap["meta"]["generated_utc"])


def test_legends_are_quantile_breaks_over_observed_values_only():
    rows = {
        "w1": [
            {"observed": True, "normal": v, "unusual": 0.5, "exposure": v, "obs_vs_exp": None}
            for v in (1.0, 2.0, 3.0, 4.0, 5.0)
        ]
        + [
            {
                "observed": False,
                "normal": None,
                "unusual": None,
                "exposure": 0.0,
                "obs_vs_exp": None,
            }
        ]
    }
    lg = _legends(rows)
    assert lg["normal"]["breaks"] == [1.0, 1.8, 2.6, 3.4, 4.2, 5.0]  # quantiles of 1..5, no zeros
    assert lg["exposure"]["breaks"] == lg["normal"]["breaks"]  # the unobserved 0.0 is left out
    assert lg["unusual"]["breaks"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert lg["obs_vs_exp"] == {"clip": 3, "breaks": []}  # no values yet (issue 87)


def test_snapshot_carries_legends_and_the_overlay_layers(world):
    _, snap = world
    geom = set(snap["cells"]["geometry"])
    cells = io.read_stage("reference/cells")
    fine = cells[cells["level"] == 2000]
    assert set(snap["cells"]["layers"]["lane"]) == set(fine.loc[fine["lane"], "cell_id"])
    assert set(snap["cells"]["layers"]["exclusion"]) == set(fine.loc[fine["exclusion"], "cell_id"])
    assert set(snap["cells"]["layers"]["inshore"]) <= geom
    breaks = snap["cells"]["legends"]["normal"]["breaks"]
    assert breaks == sorted(set(breaks)) and len(breaks) >= 2
