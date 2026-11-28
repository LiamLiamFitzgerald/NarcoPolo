import json
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from core.crs import to_utm
from core.schemas import check_json
from core.time import iso_week
from export import build_snapshot
from patrol import (
    KN_MS,
    _base,
    _greedy_inputs,
    _plan_asset,
    _Sea,
    _sea_from_cells,
    _sea_from_raster,
    _start,
    air_hours,
    aircraft_plan,
    bandit,
    greedy_route,
    sea_hours,
    ship_plan,
    two_opt,
)
from sim import patrol_outcome
from sim.simulate import simulate

RES = 250.0
KN12_M_PER_H = 12 * KN_MS * 3600


def _sea(mask) -> _Sea:
    return _Sea(np.array(mask, bool), 0.0, 0.0, RES)


def _node(col, row):  # pixel centre
    return {"x_m": (col + 0.5) * RES, "y_m": (row + 0.5) * RES}


def test_air_hours_recovers_known_distance():
    nodes = [{"x_m": 0, "y_m": 0}, {"x_m": 111_120, "y_m": 0}, {"x_m": 0, "y_m": 222_240}]
    h = air_hours(nodes)  # 60 NM and 120 NM at 180 kn
    assert np.allclose([h[0, 1], h[0, 2]], [1 / 3, 2 / 3], atol=1e-3)
    assert np.allclose(h, h.T) and np.all(np.diag(h) == 0)


def test_sea_hours_open_water_is_a_straight_line():
    h = sea_hours([_node(0, 0), _node(10, 0)], _sea(np.ones((3, 11))))
    assert h[0, 1] == pytest.approx(10 * RES / KN12_M_PER_H) and h[0, 1] == h[1, 0]


def test_sea_grid_comes_from_the_real_raster_when_it_exists(tmp_path, monkeypatch):
    import rasterio
    from rasterio.transform import from_origin

    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    assert (
        _sea_from_raster() is None
    )  # the simulator writes no raster: patrol falls back to the cells
    x0, y0 = 380_000.0, 5_660_000.0
    south_up = np.ones((3, 5), np.uint8)
    south_up[0:2, 2] = 0  # the same headland as above: land in column 2 on the two southern rows
    path = io.raster_path("reference/sea_250m")
    path.parent.mkdir(parents=True)
    with rasterio.open(  # a north-up GeoTIFF with its origin at (x0, y0), like reference.run writes
        path, "w", driver="GTiff", height=3, width=5, count=1, dtype="uint8",
        crs="EPSG:32629", transform=from_origin(x0, y0 + 3 * RES, RES, RES),
    ) as dst:  # fmt: skip
        dst.write(south_up[::-1], 1)
    sea = _sea_from_raster()
    assert sea is not None and (sea.x0, sea.y0, sea.res) == (x0, y0, RES)
    assert (sea.mask == south_up.astype(bool)).all()  # row 0 is the southern edge again
    nodes = [
        {"x_m": x0 + 0.5 * RES, "y_m": y0 + 0.5 * RES},
        {"x_m": x0 + 4.5 * RES, "y_m": y0 + 0.5 * RES},
    ]
    assert sea_hours(nodes, sea)[0, 1] == pytest.approx(4 * np.sqrt(2) * RES / KN12_M_PER_H)


def test_sea_hours_goes_round_a_headland_not_over_it():
    # 3 rows x 5 columns, land in column 2 on rows 0 and 1. From (0,0) to (4,0) the only way
    # is through (2,2): four diagonal steps, 4*sqrt(2) pixels, not the 4 of a straight line.
    mask = np.ones((3, 5))
    mask[0:2, 2] = 0
    nodes = [_node(0, 0), _node(4, 0)]
    sea = sea_hours(nodes, _sea(mask))[0, 1]
    assert sea == pytest.approx(4 * np.sqrt(2) * RES / KN12_M_PER_H)
    assert sea > 4 * RES / KN12_M_PER_H  # a straight line would cross land


def test_sea_hours_unreachable_is_infinite_and_a_pier_on_land_snaps_to_sea():
    mask = np.ones((3, 5))
    mask[:, 2] = 0  # a complete wall
    assert np.isinf(sea_hours([_node(0, 1), _node(4, 1)], _sea(mask))[0, 1])
    mask = np.ones((3, 5))
    mask[0, 0] = 0  # a pier on the shore: the node sits on land, one pixel from the sea
    assert np.isfinite(sea_hours([_node(0, 0), _node(4, 2)], _sea(mask))[0, 1])


# base at 0, sites on a line at 1, 2 and 3 hours out
LINE = np.array([[abs(i - j) for j in range(4)] for i in range(4)], float)


def test_greedy_route_picks_by_score_per_extra_hour_and_respects_the_budget():
    S = np.array([0, 1.0, 1.0, 9.0])
    # budget 8: base-3-base = 6 + 1 dwell = 7, adding site 1 or 2 on the way costs only the dwell.
    r = greedy_route([None] * 4, S, LINE, budget_h=8, dwell_h=1)
    assert (
        r[0] == r[-1] == 0 and 3 in r and len(r) == 4
    )  # base, then two stops (3 and one cheaper), base
    total = sum(LINE[a, b] for a, b in pairwise(r)) + (len(r) - 2)
    assert total <= 8
    # a tight budget keeps the high-score far site out
    assert greedy_route([None] * 4, S, LINE, budget_h=3, dwell_h=1) == [0, 1, 0]
    assert greedy_route([None] * 4, S, LINE, budget_h=0.5, dwell_h=1) == [0, 0]


def test_greedy_route_never_visits_an_unreachable_site():
    h = LINE.copy()
    h[0, 3] = h[3, 0] = h[1, 3] = h[3, 1] = h[2, 3] = h[3, 2] = np.inf
    r = greedy_route([None] * 4, np.array([0, 1.0, 1.0, 99.0]), h, budget_h=24, dwell_h=1)
    assert 3 not in r


def test_two_opt_untangles_a_crossed_route_and_keeps_the_ends():
    pts = np.array([[0, 0], [0, 1], [1, 1], [1, 0]], float)  # a unit square, base at the corner 0
    d = np.hypot(*(pts[:, None] - pts[None]).transpose(2, 0, 1))
    crossed = [0, 2, 1, 3, 0]
    fixed = two_opt(crossed, d)
    tour = lambda r: sum(d[a, b] for a, b in pairwise(r))
    assert tour(fixed) == pytest.approx(4.0) and tour(crossed) > 4.0
    assert fixed[0] == fixed[-1] == 0 and sorted(fixed) == sorted(crossed)
    assert two_opt([0, 1, 2, 3, 0], d) == [0, 1, 2, 3, 0]  # already optimal: unchanged


def _sites(n, flagged):
    """n sites on a line at x = 1 km, 2 km, ... with scores n, n-1, ... (rank 1 = best)."""
    return pd.DataFrame(
        {
            "site_id": [f"s{i}" for i in range(n)],
            "x_m": [(i + 1) * 1000.0 for i in range(n)],
            "y_m": 0.0,
            "S": [float(n - i) for i in range(n)],
            "bh_flag": [i < flagged for i in range(n)],
        }
    )


def _open_sea(nodes):
    return sea_hours(nodes, _sea(np.ones((5, 400))))


START = pd.Timestamp("2026-11-28", tz="UTC")


def test_plan_labels_unflagged_fill_sites_and_has_no_fixed_exploration_slot():
    # D3 (#176): without a Thompson draw there is no exploration visit; the route is the greedy fill on S
    sites = _sites(20, flagged=5)
    stops = _plan_asset(sites, (0.0, 0.0), _open_sea, budget_h=24, dwell_h=1, start=START)
    ids = [s["id"] for s in stops]
    assert ids[0] == ids[-1] == "base" and not any(s.get("exploration") for s in stops)
    flagged = dict(zip(sites["site_id"], sites["bh_flag"], strict=True))
    for s in stops[1:-1]:  # unflagged sites are labelled "not significant"
        assert s.get("not_significant", False) == (not flagged[s["id"]])
    assert [s["arrival_utc"] for s in stops] == sorted(s["arrival_utc"] for s in stops)


def test_thompson_explore_stops_are_the_exploration_visits():
    # D3: the bandit's draw is the one exploration method; a stop off the posterior-mean route is "explore"
    sites = _sites(20, flagged=5)
    mean = pd.Series(sites["S"].to_numpy(), index=sites["site_id"])
    theta = mean.copy()
    theta["s12"] = 100.0  # the draw favours a low-ranked site the mean route would skip
    stops = _plan_asset(
        sites, (0.0, 0.0), _open_sea, budget_h=6, dwell_h=1, start=START, theta=theta, exploit=mean
    )
    explore = [s["id"] for s in stops if s.get("exploration")]
    assert "s12" in explore
    assert all(s["reason"] == "explore" for s in stops if s.get("exploration"))
    assert all(s.get("exploration", False) == (s["reason"] == "explore") for s in stops[1:-1])


def test_greedy_inputs_put_flagged_sites_first_then_fill_by_score():
    sites = _sites(20, flagged=0).assign(bh_flag=lambda d: d["site_id"].isin(["s7", "s9"]))
    top = _greedy_inputs(sites)
    assert list(top["site_id"][:2]) == ["s7", "s9"] and len(top) == 15
    assert list(top["site_id"][2:5]) == ["s0", "s1", "s2"]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("w")
    mp.setenv("NARCO_DATA", str(root / "data"))
    mp.setenv("NARCO_REPORTS", str(root / "reports"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    ship_plan()
    aircraft_plan()
    yield root, json.loads((root / "data" / "patrol" / "plan.json").read_text())
    mp.undo()


def test_simulator_plans_stay_in_budget_start_and_end_at_the_base(world):
    _, plan = world
    assert set(plan) == {"ship", "aircraft"}
    sites = set(io.read_stage("fuse/sites")["site_id"])
    for asset, budget in (("ship", 24), ("aircraft", 4)):
        stops = plan[asset]
        assert stops[0]["id"] == stops[-1]["id"] == "base"
        assert {s["id"] for s in stops[1:-1]} <= sites
        t = pd.to_datetime([s["arrival_utc"] for s in stops])
        assert (t[-1] - t[0]).total_seconds() / 3600 <= budget
        assert all(s["arrival_utc"].endswith("Z") for s in stops)  # ISO strings (A12)
    assert any(s["id"] != "base" for s in plan["ship"])  # the planted site is worth a visit


def test_simulator_ship_stops_are_reachable_by_sea(world):
    _, plan = world
    nodes = [{"x_m": s["x_m"], "y_m": s["y_m"]} for s in plan["ship"]]
    h = sea_hours(nodes, _sea_from_cells(io.read_stage("reference/cells")))
    assert np.isfinite(h).all()


def test_patrol_plan_feeds_the_export(world):
    _, plan = world
    snap = build_snapshot()
    assert [s["id"] for s in snap["plan"]["ship"]] == [s["id"] for s in plan["ship"]]
    assert all("lon" in s for s in snap["plan"]["aircraft"])
    assert date.fromisoformat(snap["meta"]["T"]) < date.fromisoformat(
        plan["ship"][0]["arrival_utc"][:10]
    )


def test_base_and_start_come_from_config_never_from_a_guess(world, monkeypatch):
    import patrol

    (x, y), stand_in = _base({"patrol": {"base_port": {"lon": -8.0, "lat": 51.5}}})
    assert _base({"base_port": {"lon": -8.0, "lat": 51.5}})[0] == (x, y)  # top-level form read too
    ex, ey = to_utm(-8.0, 51.5)
    assert (x, y) == pytest.approx((float(ex), float(ey))) and not stand_in
    start, stand_in = _start({"patrol": {"start_hour_utc": 6}})
    assert start == pd.Timestamp("2026-11-28 06:00", tz="UTC") and not stand_in
    # no config: simulated data gets a stand-in (the first road pier), flagged as such
    (px, py), stand_in = _base({})
    piers = io.read_stage("reference/piers")
    first = piers[piers["road_access"]].sort_values("pier_id").geometry.iloc[0]
    assert (px, py) == (first.x, first.y) and stand_in
    assert _start({})[0] == pd.Timestamp("2026-11-28 00:00", tz="UTC") and _start({})[1]
    # no config: real data refuses to run
    monkeypatch.setattr(patrol, "_provenance", lambda name: "real")
    for call in (_base, _start):
        with pytest.raises(ValueError, match="issue 103"):
            call({})


def test_plans_with_stand_ins_say_so_and_pass_the_contract(world):
    _, plan = world
    assert all(s.get("stand_in") for a in plan.values() for s in (a[0], a[-1]))
    check_json("patrol/plan", io.read_json_stage("patrol/plan"))


def test_simulator_plans_carry_bandit_fields_and_save_the_state(world):
    _, plan = world
    for stops in plan.values():
        assert all(
            s["reason"] in ("exploit", "explore") and 0 <= s["theta"] <= 1 for s in stops[1:-1]
        )
    state = io.read_json_stage("patrol/bandit_state")  # checked against the contract on read
    assert {s["id"] for a in plan.values() for s in a[1:-1]} <= set(state)


def test_simulated_patrol_outcomes_update_only_visited_sites(world):
    """End to end: plan -> sim.patrol_outcome on the simulator truth -> bandit.update."""
    _, plan = world
    state = io.read_json_stage("patrol/bandit_state")
    week = iso_week(io.read_snapshot()["T"])[1]
    out = patrol_outcome(pd.read_parquet(io.truth_path()), plan, week)
    new = bandit.update(state, out, discount=0.9, week=week)
    visits = out[out["site_id"].isin(state)].groupby("site_id")["found"].agg(["sum", "count"])
    for site, st in state.items():
        found, n = (
            (visits.loc[site, "sum"], visits.loc[site, "count"]) if site in visits.index else (0, 0)
        )
        assert new[site]["alpha"] == pytest.approx(0.9 * st["alpha"] + found)
        assert new[site]["beta"] == pytest.approx(0.9 * st["beta"] + n - found)
        assert (new[site]["last_visit_week"] == week) == bool(
            n
        )  # n is a count, so nonzero means visited
    check_json("patrol/bandit_state", new)


def test_patrol_parameters_are_the_spec_values_overlaid_by_config():
    # #89: docs/specs/P7.md Parameters, and config.yaml's `patrol:` block wins once P1 adds it
    import patrol
    from core import io
    from core.config import load

    cfg = dict(load(io.CONFIG_PATH)[0].get("patrol", {}))
    want = {**patrol._SPEC, **cfg}
    assert patrol.TOP_SITES == want["top_sites"] and patrol.SHIP_KN == want["ship_kn"]
    assert (patrol.SHIP_BUDGET_H, patrol.SHIP_DWELL_H) == (
        want["ship_budget_h"],
        want["ship_dwell_h"],
    )
    assert (patrol.AIR_KN, patrol.AIR_BUDGET_H, patrol.AIR_DWELL_H) == (
        want["aircraft_kn"], want["aircraft_budget_h"], want["aircraft_dwell_h"],
    )  # fmt: skip


def _record(rows):
    """patrol/outcomes rows (site_id, iso_week, outcome), entered in order, as the dashboard writes them."""
    t0 = pd.Timestamp("2026-11-20", tz="UTC")
    f = pd.DataFrame(rows, columns=["site_id", "iso_week", "outcome"])
    f["entered_at"] = [t0 + pd.Timedelta(minutes=i) for i in range(len(f))]
    io.write_stage("patrol/outcomes", f, "real")


def test_crew_outcomes_move_next_weeks_draw(world):  # #339: patrol reads patrol/outcomes (#329)
    T = io.read_snapshot()["T"]
    plan_week = iso_week(T + timedelta(days=1))
    y, w, _ = (date.fromisocalendar(*plan_week, 1) - timedelta(days=7)).isocalendar()
    last, now = f"{y}-W{w:02d}", f"{plan_week[0]}-W{plan_week[1]:02d}"
    cfg = load(io.CONFIG_PATH)[0]
    sites = io.read_stage("fuse/sites")
    prior = bandit._mean(bandit.prior(_greedy_inputs(sites), cfg["learn"]["prior_strength"]))
    a, b, c, d = list(prior.index[:4])
    try:
        _record([
            (a, last, "found_something"),  # corrected below: the latest answer wins
            (a, last, "found_nothing"),
            (b, last, "found_something"),
            (c, last, "not_visited"),  # never a "found nothing"
            (d, now, "found_something"),  # the plan week itself: after the cut-off, ignored
        ])  # fmt: skip
        ship_plan()
        mean = bandit._mean(io.read_json_stage("patrol/bandit_state"))
        assert mean[a] < prior[a] and mean[b] > prior[b]
        k = cfg["learn"]["discount"]
        for s in (c, d):  # only the weekly discount, which leaves the mean unchanged
            assert mean[s] == pytest.approx(prior[s])
        st = io.read_json_stage("patrol/bandit_state")
        assert st[c]["alpha"] == pytest.approx(
            k * bandit.prior(_greedy_inputs(sites), cfg["learn"]["prior_strength"])[c]["alpha"]
        )
        ship_plan()  # rerunning counts nothing twice
        assert io.read_json_stage("patrol/bandit_state") == st
    finally:
        io.stage_path("patrol/outcomes").unlink()
    ship_plan()  # no file: back to the priors
    assert bandit._mean(io.read_json_stage("patrol/bandit_state")).equals(prior)
