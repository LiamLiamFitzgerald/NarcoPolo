import json
import struct
import zlib
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
    _backdrop,
    _basemap,
    _daily,
    _legends,
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


def test_snapshot_sites_match_the_stage_file(world):
    _, snap = world
    sites = io.read_stage("fuse/sites")
    score = dict(zip(sites["site_id"], sites["S"], strict=True))
    assert [s["id"] for s in snap["sites"]] == sorted(score, key=lambda i: -score[i])
    assert all(len(s["top_piers"]) <= 3 and isinstance(s["reasons"], list) for s in snap["sites"])
    assert np.isfinite([s["S"] for s in snap["sites"]]).all()
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
    assert kinds == ["study_area", "land"]  # the simulator writes reference/land (#133)
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
    assert fig["sites"] == len(snap["sites"]) and fig["flagged"] == sum(
        s["bh_flag"] for s in snap["sites"]
    )
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
    assert {s["lens"] for s in snap["sites"]} == {"dropoff"}  # fisheries sites arrive with #321


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
    _, snap = world
    for s in snap["sites"]:
        assert s["checks"] == {"rare_slowdown": None, "boats_after": None, "outside_fishing": None}
        assert s["top_pier_minutes"] == [None] * len(s["top_piers"])  # PLACEHOLDER (#320)
        assert all(p["seen"] is None for e in s["timeline"] for p in e["passes"])
        assert all(e["date"] >= "2026-11-02" for e in s["timeline"])  # within the shown weeks


def test_plan_stops_carry_their_lens_and_only_the_zero_mix_is_ready(world):
    _, snap = world
    ship = snap["plan"]["ship"]
    assert "lens" not in ship[0] and ship[1]["lens"] == "dropoff" and ship[1]["reason"] == "explore"
    assert snap["meta"]["mission_mix"] == {"wanted": [0], "ready": [0]}  # PLACEHOLDER (#316, #321)


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


# Radar backdrop from raw/s1 (#387), on hand-built scenes
def _scene(root, sid, when, x0, value, simulated=True):
    import rasterio
    from rasterio.transform import from_origin

    (root / "s1").mkdir(parents=True, exist_ok=True)
    with rasterio.open(  # 20 x 20 px at 10 m, VV then VH, dB x 100 like raw/s1
        root / "s1" / f"{sid}.tif", "w", driver="GTiff", height=20, width=20, count=2, dtype="int16",
        crs="EPSG:32629", transform=from_origin(x0, 5_700_200.0, 10.0, 10.0),
    ) as dst:  # fmt: skip
        dst.write(np.full((2, 20, 20), value, np.int16))
    (root / "s1" / f"{sid}.json").write_text(json.dumps({"scene_id": sid, "start_time": when}))
    m = root / "manifest.json"
    man = json.loads(m.read_text()) if m.exists() else {"files": {}}
    man["files"][f"s1/{sid}.tif"] = {"request": {"simulated": simulated}}
    m.write_text(json.dumps(man))


def _decode(png):
    from rasterio.io import MemoryFile

    with MemoryFile(png) as mem, mem.open() as src:
        return src.read()


def test_raw_backdrop_latest_scene_wins_and_uncovered_is_transparent(tmp_path):
    from export import _raw_backdrop

    # a: x 500000-500200 (old, dark); b: x 500100-500300 (new, bright); c is after T and never shown
    _scene(tmp_path, "a", "2026-11-20T06:00:00Z", 500_000.0, -2500)
    _scene(tmp_path, "b", "2026-11-26T06:00:00Z", 500_100.0, -1500)
    _scene(tmp_path, "c", "2026-11-29T06:00:00Z", 500_000.0, -1000)
    png, meta = _raw_backdrop(tmp_path, date(2026, 11, 28))
    grey, alpha = _decode(png)
    assert png.startswith(b"\x89PNG") and len(png) < 1_000_000
    assert (meta["from"], meta["to"]) == ("2026-11-20", "2026-11-26")  # c is after T
    assert grey.shape[1] == 30  # 300 m at the scenes' 10 m
    assert alpha.min() == 255 and alpha.max() == 255  # this footprint is fully covered
    left, right = grey[10, 2], grey[10, -3]
    assert left == 0 and right == 255  # the dark old scene, then the bright newer one on top
    assert grey[10, 15] == 255  # the overlap shows the latest scene
    lon0, lat0, lon1, lat1 = meta["bounds"]
    assert lon0 < lon1 and lat0 < lat1 and abs(lon0 + 9.0) < 0.01 and 51.4 < lat0 < 51.5
    assert meta["attribution"].startswith(
        "Simulated"
    )  # the manifest says so; never a Copernicus credit


def test_raw_backdrop_leaves_gaps_transparent_and_credits_real_scenes(tmp_path):
    from export import _raw_backdrop

    _scene(tmp_path, "a", "2026-11-20T06:00:00Z", 500_000.0, -2500, simulated=False)
    _scene(tmp_path, "b", "2026-11-21T06:00:00Z", 500_400.0, -1500, simulated=False)  # a 200 m gap
    png, meta = _raw_backdrop(tmp_path, date(2026, 11, 28))
    _, alpha = _decode(png)
    assert alpha[10, 30] == 0 and alpha[10, 5] == 255  # not looked at: transparent, not black
    assert meta["attribution"] == "Contains modified Copernicus Sentinel data 2026"
    assert _raw_backdrop(tmp_path, date(2026, 11, 1)) is None  # no scene up to T: no backdrop


def test_simulator_scenes_make_a_labelled_backdrop_up_to_T(world):
    # #387: the simulator writes raw/s1 like P2 does; the composite covers its scenes up to T and says it is simulated
    from export import _raw_backdrop, _scenes

    t = io.read_snapshot()["T"]
    scenes = _scenes(io.raw_root(), t)
    assert scenes and all(when.date() <= t for when, _ in scenes)
    png, meta = _raw_backdrop(io.raw_root(), t)
    bd = _backdrop(png, meta)  # the same checks as P3's file: a PNG under 1 MB with 4 bounds
    assert (
        bd["attribution"].startswith("Simulated") and bd["to"] == scenes[-1][0].date().isoformat()
    )
    region = load(io.CONFIG_PATH)[0]["region_bbox"]
    lon0, lat0, lon1, lat1 = bd["bounds"]
    assert region["lon_min"] - 0.5 < lon0 < lon1 < region["lon_max"] + 0.5
    assert region["lat_min"] - 0.5 < lat0 < lat1 < region["lat_max"] + 0.5
