import json
import struct
import zlib
from datetime import UTC, date, datetime

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from core import io
from core.config import load
from core.crs import to_utm
from core.schemas import SCHEMAS, check_json
from export import (
    _backdrop,
    _basemap,
    _closed_area_features,
    _daily,
    _fisheries_candidates,
    _fisheries_sites,
    _legends,
    _mission_mix,
    _provenance,
    _scan,
    _timeline,
    _weeks,
    basemap,
    build_snapshot,
    data_label,
    heatmap_values,
    scan_identities,
)
from sim.simulate import simulate

WEEK = "2026-W48"  # Monday 2026-11-23 to Sunday 2026-11-29


def _png(w: int = 4, h: int = 2) -> bytes:
    """A valid 8-bit greyscale PNG, w x h, a left-to-right gradient."""
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    rows = b"".join(b"\x00" + bytes(255 * x // max(w - 1, 1) for x in range(w)) for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


BACKDROP_META = {
    "bounds": [-10.6, 51.1, -7.9, 51.95],
    "crs": "EPSG:4326",
    "from": "2026-08-30",
    "to": "2026-11-27",
    "n_scenes": 30,
    "attribution": "Contains modified Copernicus Sentinel data 2026",
}


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
            "y_week": [1.0, 2.0, 8.0, 1.0],
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
    # obs_vs_exp = log2(y_week) of the week's dark_small row: A's is 2.0 -> 1.0 (its slowdown row and last
    # week's 8.0 don't count); no dark_small row this week -> None, never 0
    assert a["obs_vs_exp"] == 1.0
    assert all(got[c]["obs_vs_exp"] is None for c in ("B", "C", "D"))


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
                 {**stop(s.site_id, "2026-11-27T08:00:00Z", s.x_m, s.y_m), "exploration": True, "reason": "explore"},
                 stop("base", "2026-11-27T10:00:00Z", s.x_m - 9000, s.y_m)],
        "aircraft": [],
    }  # fmt: skip
    io.write_json_stage("patrol/plan", plan, "simulated")
    ref = io.stage_path(
        "reference/cells"
    ).parent  # the radar backdrop P3 will write (contract #263)
    (ref / "radar_backdrop.png").write_bytes(_png())
    (ref / "radar_backdrop.json").write_text(json.dumps(BACKDROP_META))
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
    assert snap["meta"]["top_sites"] == 15  # patrol.top_sites in config.yaml
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
    # the bandit marks its exploration visits with reason "explore" (D3); the dashboard needs it
    assert [s.get("reason") for s in snap["plan"]["ship"]] == [None, "explore", None]
    pj = io.read_stage("fuse/piers").set_index("pier_id")["P_j"]
    assert snap["piers"] and all(
        p["P_j"] == pytest.approx(pj[p["id"]], abs=1e-4) for p in snap["piers"]
    )


def _dropoff(snap):
    return [s for s in snap["sites"] if s["lens"] == "dropoff"]


def test_snapshot_sites_match_the_stage_file(world):
    _, snap = world
    sites = io.read_stage("fuse/sites")
    score = dict(zip(sites["site_id"], sites["S"], strict=True))
    assert [s["id"] for s in _dropoff(snap)] == sorted(score, key=lambda i: -score[i])
    assert all(len(s["top_piers"]) <= 3 and isinstance(s["reasons"], list) for s in snap["sites"])
    assert np.isfinite([s["S"] for s in _dropoff(snap)]).all()
    assert datetime.fromisoformat(snap["meta"]["generated_utc"])
    # D1 (#176): the merged agreement the dashboard shows comes from fuse/sites (None where it has none)
    merged = sites.set_index("site_id").get("agreement_merged")
    for s in snap["sites"]:
        want = None if merged is None or pd.isna(merged[s["id"]]) else int(merged[s["id"]])
        assert s["agreement_merged"] == want


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
    assert lg["obs_vs_exp"] == {"clip": 3, "breaks": []}  # no obs_vs_exp values in these rows


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


def test_backdrop_is_an_embedded_png_with_its_bounds_and_attribution():
    bd = _backdrop(_png(), BACKDROP_META)
    assert bd["image"].startswith("data:image/png;base64,")
    assert bd["bounds"] == BACKDROP_META["bounds"] and "Copernicus" in bd["attribution"]
    assert (bd["from"], bd["to"]) == ("2026-08-30", "2026-11-27")
    with pytest.raises(ValueError, match="PNG"):
        _backdrop(b"GIF89a....", BACKDROP_META)
    with pytest.raises(ValueError, match="1 MB"):
        _backdrop(_png()[:8] + bytes(1_000_001), BACKDROP_META)
    with pytest.raises(ValueError, match="bounds"):
        _backdrop(_png(), {**BACKDROP_META, "bounds": [1, 2, 3]})


def test_the_image_is_not_text_so_the_identity_scan_skips_it_but_not_the_rest():
    snap = {
        "basemap": {"backdrop": {"image": "data:image/png;base64,+123456789+", "attribution": "x"}}
    }
    with pytest.raises(ValueError):
        scan_identities(snap)  # base64 can contain a 9-digit run by chance
    _scan(snap)  # the export scan ignores the pixels
    with pytest.raises(ValueError):
        _scan({**snap, "sites": [{"reasons": ["id 123456789"]}]})  # but still scans everything else


def test_snapshot_embeds_the_radar_backdrop_when_p3_has_written_it(world):
    _, snap = world
    bd = snap["basemap"]["backdrop"]
    assert (
        bd["image"].startswith("data:image/png;base64,") and bd["bounds"] == BACKDROP_META["bounds"]
    )
    check_json("export/snapshot", snap)  # still exactly the seven top-level keys


def test_basemap_draws_land_when_the_land_layer_exists_and_only_the_outline_otherwise():
    x, y = (float(v) for v in to_utm(-9.0, 51.5))
    sea = Polygon([(x, y), (x + 10_000, y), (x + 10_000, y + 5_000), (x, y + 5_000)])
    land = Polygon(
        [(x, y + 5_000), (x + 10_000, y + 5_000), (x + 10_000, y + 9_000), (x, y + 9_000)]
    )
    assert [f["properties"]["kind"] for f in _basemap(sea, None)["features"]] == ["study_area"]
    fc = _basemap(sea, land)
    assert [f["properties"]["kind"] for f in fc["features"]] == ["study_area", "land"]
    lon, lat = fc["features"][1]["geometry"]["coordinates"][0][0]
    assert abs(lon + 9.0) < 1e-3 and 51.5 < lat < 51.6  # land north of the sea, in WGS 84


def test_snapshot_basemap_has_the_simulated_land(world):
    _, snap = world
    kinds = [f["properties"]["kind"] for f in snap["basemap"]["features"]]
    assert kinds[:2] == ["study_area", "land"]  # the simulator writes reference/land (#133)
    assert set(kinds[2:]) <= {"closed_area"}  # and reference/closed_areas once #360 is in (#322)
    # the land lies along the simulated grid (which starts at x0, a little west of region_bbox)
    boxes = list(snap["cells"]["geometry"].values())
    west, east = min(b[0] for b in boxes), max(b[2] for b in boxes)
    ring = snap["basemap"]["features"][1]["geometry"]["coordinates"][0]
    assert all(west - 0.01 <= lon <= east + 0.01 for lon, _ in ring)


def test_daily_series_matches_a_hand_count_and_leaves_unobserved_days_empty():
    # day 1: one pass covers c1 (calm, small-boat exposure) and c2 (covered but rough); c3, c4 not covered.
    # fuse/cells: c1 unusual (U 0.95, flagged), c2 not. Day 2: no pass and no rows: every value is None.
    ex = pd.DataFrame({"cell_id": ["c1", "c2"], "pass_id": ["p1", "p1"], "time_utc": [_t("2026-11-23")] * 2,
                       "covered_frac": [0.5, 0.3], "exposure_small": [0.5, 0.0]})  # fmt: skip
    fz = pd.DataFrame({"cell_id": ["c1", "c2"], "date": [date(2026, 11, 23)] * 2, "U": [0.95, 0.5],
                       "bh_flag": [True, False]})  # fmt: skip
    d1, d2 = _daily(fz, ex, ["c1", "c2", "c3", "c4"], [date(2026, 11, 23), date(2026, 11, 24)])
    assert d1 == {"date": "2026-11-23", "passes": 1, "covered_share": 0.5, "calm_share": 0.25,
                  "unusual_cells": 1, "flagged_cells": 1}  # fmt: skip
    assert d2 == {"date": "2026-11-24", "passes": 0, "covered_share": None, "calm_share": None,
                  "unusual_cells": None, "flagged_cells": None}  # fmt: skip


def test_snapshot_carries_chart_data_inside_the_existing_keys(world):
    _, snap = world
    check_json("export/snapshot", snap)  # still exactly the seven top-level keys
    fig = snap["meta"]["figures"]
    assert fig["sites"] == len(_dropoff(snap)) and fig["flagged"] == sum(
        s["bh_flag"] for s in _dropoff(snap)
    )
    assert fig["fisheries"] == len(snap["sites"]) - len(_dropoff(snap))
    assert fig["ship_h"] == 4.0 and fig["ship_budget_h"] == 24.0  # the fixture plan: 06:00 to 10:00
    assert 0 <= fig["observed_share"] <= 1
    assert [s["at_h"] for s in snap["plan"]["ship"]] == [0.0, 2.0, 4.0]
    daily = snap["cells"]["daily"]
    assert daily[0]["date"] == "2026-11-02" and daily[-1]["date"] == "2026-11-27"  # W45 Monday to T
    assert all(d["covered_share"] is None for d in daily if d["passes"] == 0)  # no pass is not 0


def test_site_links_add_up_to_the_score_and_p_site_is_passed_on(world):
    _, snap = world
    sites = io.read_stage("fuse/sites")
    p_site = dict(zip(sites["site_id"], sites["p_site"], strict=True)) if "p_site" in sites else {}
    for s in snap["sites"]:
        if s[
            "links"
        ]:  # S = sum of L with a 30-day half-life (Measures), so the weights add up to S
            assert sum(k["weight"] for k in s["links"]) == pytest.approx(s["S"], rel=1e-3, abs=1e-3)
        want = p_site.get(s["id"])  # optional column: the simulator may not write it
        assert s["p_site"] == (
            None if want is None or np.isnan(want) else pytest.approx(want, abs=1e-4)
        )


def test_cells_carry_a_plain_ratio_and_sites_a_lens(world):
    _, snap = world
    rows = [c for w in snap["cells"]["weeks"].values() for c in w]
    with_ratio = [c for c in rows if c["ratio"] is not None]
    assert with_ratio and all(c["obs_vs_exp"] is not None for c in with_ratio)
    for c in with_ratio[:50]:  # obs_vs_exp is log2 of the same ratio (both rounded to 4 places)
        assert 2 ** c["obs_vs_exp"] == pytest.approx(c["ratio"], rel=2e-3, abs=2e-4)
    assert all(c["ratio"] is None for c in rows if c["obs_vs_exp"] is None)  # unobserved stays None
    lenses = {s["lens"] for s in snap["sites"]}
    has_fish = "fuse/fisheries" in SCHEMAS and io.stage_path("fuse/fisheries").exists()
    assert lenses == ({"dropoff", "fisheries"} if has_fish else {"dropoff"})  # fisheries with #321


def test_simulator_fisheries_cards_recover_the_planted_closure(world):
    # #346: the simulator plants illegal fishing in a closure; with #360 merged the lens must show it
    _, snap = world
    if "fuse/fisheries" not in SCHEMAS or not io.stage_path("fuse/fisheries").exists():
        pytest.skip("fuse/fisheries (#360) not merged yet")
    fish = [s for s in snap["sites"] if s["lens"] == "fisheries"]
    top = load(io.CONFIG_PATH)[0]["patrol"]["top_sites"]
    assert 0 < len(fish) <= top and len({s["week"] for s in fish}) == 1
    assert fish[0]["flag"] and fish[0]["in_closed_area"] is True  # the planted closure ranks first
    assert all(s["y_fish_lo"] <= s["y_fish_hi"] and s["S"] is None for s in fish)
    kinds = {f["properties"].get("type") for f in snap["basemap"]["features"]
             if f["properties"]["kind"] == "closed_area"}  # fmt: skip
    assert kinds == {"closure", "protected_area"}


def test_timeline_lists_each_slowdown_with_the_passes_after_it():
    # T = 27 Nov. Site a: slowdowns 4 and 20 days ago; the old one is before the shown weeks (from 10 Nov).
    # Passes over a: 24 Nov calm, 25 Nov rough, 26 Nov not covered (no look); site b: no pass at all.
    links = pd.DataFrame(
        {"site_id": ["a", "a", "b"], "L": [0.4, 0.9, 0.0], "age_days": [4.0, 20.0, 2.0]}
    )
    ex = pd.DataFrame({"cell_id": ["a", "a", "a"], "time_utc": [_t("2026-11-24"), _t("2026-11-25"), _t("2026-11-26")],
                       "covered_frac": [0.6, 0.6, 0.0], "exposure_small": [0.5, 0.0, 0.0]})  # fmt: skip
    tl = _timeline(links, ex, date(2026, 11, 27), date(2026, 11, 10), 7)
    assert tl["a"] == [{"date": "2026-11-23", "L": 0.4, "passes": [
        {"date": "2026-11-24", "state": "calm", "seen": None},
        {"date": "2026-11-25", "state": "rough", "seen": None}]}]  # fmt: skip
    assert tl["b"] == [
        {"date": "2026-11-25", "L": 0.0, "passes": []}
    ]  # no pass: an empty list, not "nothing seen"
    short = _timeline(
        links, ex, date(2026, 11, 27), date(2026, 11, 10), 1
    )  # link_days cuts the window
    assert [p["date"] for p in short["a"][0]["passes"]] == ["2026-11-24"]


def test_site_cards_carry_placeholder_checks_and_pier_times_until_p6_writes_them(world):
    # before #360 the simulator's fuse/sites has no #320 columns: every check and time is None, never False
    # or 0; once it carries them, the card shows them (hours x 60 = minutes)
    _, snap = world
    stage = io.read_stage("fuse/sites").set_index("site_id")
    cols = {"rare_slowdown": "check_rare_slowdown", "boats_after": "check_followup_seen",
            "outside_fishing": "check_outside_fishing"}  # fmt: skip
    for s in (x for x in snap["sites"] if x["lens"] == "dropoff"):
        row = stage.loc[s["id"]]
        for k, col in cols.items():
            v = row.get(col)
            assert s["checks"][k] == (None if v is None or pd.isna(v) else bool(v))
        hours = row.get("top_piers_hours")
        want = [None] * len(s["top_piers"]) if hours is None else [round(h * 60, 4) for h in hours]
        assert s["top_pier_minutes"] == want[:3]
        assert all(p["seen"] is None for e in s["timeline"] for p in e["passes"])
        assert all(e["date"] >= "2026-11-02" for e in s["timeline"])  # within the shown weeks


def test_plan_stops_carry_their_lens_and_only_the_zero_mix_is_ready(world):
    _, snap = world
    ship = snap["plan"]["ship"]
    assert "lens" not in ship[0] and ship[1]["lens"] == "dropoff" and ship[1]["reason"] == "explore"
    mm = snap["meta"][
        "mission_mix"
    ]  # the fixture writes no plan_mixes.json: only the 0 % plan is ready
    assert mm["ready"] == [0] and mm["plans"] == {} and 0 in mm["wanted"]
    want = load(io.CONFIG_PATH)[0]["patrol"].get("mission_mixes", [0])
    assert mm["wanted"] == sorted({0, *want})


def test_headline_figures_match_a_hand_count_on_the_simulator(world):
    # #279: every figure in the strip comes from the snapshot, checked against its source here
    _, snap = world
    fig, sites = snap["meta"]["figures"], io.read_stage("fuse/sites")
    cfg = load(io.CONFIG_PATH)[0]["patrol"]
    assert fig["sites"] == len(sites) and fig["flagged"] == int(sites["bh_flag"].sum())
    assert fig["candidates"] == min(cfg["top_sites"], len(sites))
    assert fig["aircraft_h"] is None  # the fixture plan has no aircraft stops: unknown, not 0 h
    week = snap["cells"]["weeks"][snap["meta"]["week"]]
    assert fig["observed_share"] == pytest.approx(sum(c["observed"] for c in week) / len(week))


# Fisheries lens (#321, #322) on hand-built frames
def _fish(rows):
    base = {"count": 1.0, "mu": 0.5, "p_mid": 0.01, "y_fish_lo": 1.0, "y_fish_hi": 3.0, "reasons": ["r"],
            "top_harbours": ["p1", "p2"], "top_harbours_hours": [0.5, 1.25], "lens": "fisheries"}  # fmt: skip
    return pd.DataFrame([{**base, **r} for r in rows]).assign(
        week=lambda d: pd.to_datetime(d["week"]),
        in_closed_area=lambda d: d["in_closed_area"].astype("boolean"),
    )


def test_fisheries_candidates_use_the_latest_week_up_to_T_flagged_first():
    fish = _fish([
        {"cell_id": "a", "week": "2026-11-16", "y_fish": 9.0, "flag": True, "in_closed_area": True},
        {"cell_id": "b", "week": "2026-11-23", "y_fish": 5.0, "flag": False, "in_closed_area": None},
        {"cell_id": "c", "week": "2026-11-23", "y_fish": 2.0, "flag": True, "in_closed_area": False},
        {"cell_id": "d", "week": "2026-11-23", "y_fish": 3.0, "flag": True, "in_closed_area": True},
        {"cell_id": "e", "week": "2026-11-30", "y_fish": 99.0, "flag": True, "in_closed_area": True},
    ])  # fmt: skip
    got = _fisheries_candidates(fish, date(2026, 11, 28), top=2)
    assert list(got["cell_id"]) == [
        "d",
        "c",
    ]  # W48 only (e is after T, a older); flagged, then y_fish
    assert _fisheries_candidates(fish, date(2026, 11, 1), top=2).empty  # nothing up to T


def test_fisheries_sites_carry_their_fields_and_no_made_up_drop_off_numbers():
    x, y = (float(v) for v in to_utm(-9.0, 51.5))
    ref = pd.DataFrame(
        {
            "cell_id": ["b"],
            "geometry": [Polygon([(x, y), (x + 2000, y), (x + 2000, y + 2000), (x, y + 2000)])],
        }
    )
    ref = gpd.GeoDataFrame(ref, crs=32629)
    fish = _fish(
        [
            {
                "cell_id": "b",
                "week": "2026-11-23",
                "y_fish": 5.0,
                "flag": False,
                "in_closed_area": None,
            }
        ]
    )
    (s,) = _fisheries_sites(fish, ref)
    assert s["id"] == "b" and s["lens"] == "fisheries" and s["week"] == "2026-11-23"
    assert (s["y_fish"], s["y_fish_lo"], s["y_fish_hi"]) == (5.0, 1.0, 3.0)
    assert s["in_closed_area"] is None  # NA: no closed-areas layer covers the cell, never "outside"
    assert s["top_piers"] == ["p1", "p2"] and s["top_pier_minutes"] == [30.0, 75.0]
    assert abs(s["lon"] + 8.9857) < 1e-3  # the cell centre, 1 km east of its corner
    for k in ("S", "p_perm", "bh_flag", "recurrence", "agreement", "followup_unobserved", "p_site"):
        assert s[k] is None, k
    assert s["links"] == [] and s["timeline"] == [] and set(s["checks"].values()) == {None}


def test_closed_areas_become_wgs84_basemap_features_with_name_and_type():
    x, y = (float(v) for v in to_utm(-9.0, 51.5))
    areas = pd.DataFrame({"name": ["Area A"], "type": ["closure"],
                          "geometry": [Polygon([(x, y), (x + 4000, y), (x + 4000, y + 4000)])]})  # fmt: skip
    (f,) = _closed_area_features(areas)
    assert f["properties"] == {"kind": "closed_area", "name": "Area A", "type": "closure"}
    lon, lat = f["geometry"]["coordinates"][0][0]
    assert abs(lon + 9.0) < 1e-3 and abs(lat - 51.5) < 1e-3
    sea = Polygon([(x, y), (x + 10, y), (x + 10, y + 10)])
    kinds = [g["properties"]["kind"] for g in _basemap(sea, None, areas)["features"]]
    assert kinds == ["study_area", "closed_area"]


def test_mission_mix_offers_only_mixes_patrol_planned_for_this_T():
    stop = {
        "id": "base",
        "arrival_utc": "2026-11-29T00:00:00Z",
        "dwell_h": 0,
        "x_m": 500000.0,
        "y_m": 5700000.0,
    }
    fish_stop = {**stop, "id": "c9", "lens": "fisheries", "dwell_h": 1}
    p = {"ship": [stop, fish_stop, stop], "aircraft": [stop, stop]}
    cfg = {"patrol": {"mission_mixes": [0, 25, 50]}}
    mixes = {"T": "2026-11-28", "plans": {"25": p, "50": {"ship": [stop]}, "75": p}}
    mm = _mission_mix(cfg, mixes, date(2026, 11, 28), {"c9": "dropoff"})
    assert mm["wanted"] == [0, 25, 50] and mm["ready"] == [
        0,
        25,
    ]  # 50 lacks aircraft, 75 not wanted
    assert (
        mm["plans"]["25"]["ship"][1]["lens"] == "fisheries"
    )  # the stop's own lens wins over the id
    assert _mission_mix(cfg, mixes, date(2026, 11, 29), {})["ready"] == [
        0
    ]  # made for another T: stale
    assert _mission_mix({}, None, date(2026, 11, 28), {}) == {
        "wanted": [0],
        "ready": [0],
        "plans": {},
    }


@pytest.mark.slow  # a whole simulated season through detectors and fuse, ~15 s
def test_simulator_drop_site_card_recovers_p6_checks_and_pier_hours(tmp_path, monkeypatch):
    # #320 / #337: with P6's columns declared (#360), seed 1 sees a planted pick-up on a calm pass; its card
    # carries all three checks; every card's pier minutes are reference/travel_hours x 60, in top_piers order
    if "check_rare_slowdown" not in SCHEMAS["fuse/sites"].columns:
        pytest.skip("fuse/sites #320 columns (#360) not merged yet")
    import detectors
    import fuse
    from patrol import aircraft_plan, ship_plan

    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path / "reports"))
    simulate(load(io.CONFIG_PATH)[0], 1)
    detectors.run_cells()
    fuse.run()
    ship_plan()
    aircraft_plan()
    snap = build_snapshot()
    truth = pd.read_parquet(io.truth_path())
    planted = str(truth.loc[truth["kind"] == "drop", "cell_id"].iloc[0])
    (card,) = [s for s in snap["sites"] if s["id"] == planted and s["lens"] == "dropoff"]
    assert card["checks"] == {"rare_slowdown": True, "boats_after": True, "outside_fishing": True}
    # fuse lists piers only for some sites (none for the planted one on this seed): check every card that has them
    t = io.read_stage("reference/travel_hours").set_index(["cell_id", "pier_id"])["hours"]
    with_piers = [s for s in snap["sites"] if s["lens"] == "dropoff" and s["top_piers"]]
    assert with_piers
    for s in with_piers:
        want = [float(t[(s["id"], p)]) * 60 for p in s["top_piers"]]
        assert s["top_pier_minutes"] == pytest.approx(want, abs=1e-3)
