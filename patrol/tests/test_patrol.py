import json

import numpy as np

from patrol import (
    air_hours,
    aircraft_plan,
    exploration_pick,
    greedy_route,
    sea_hours,
    ship_plan,
    two_opt,
)

NODES = [{"x_m": 0, "y_m": 0}, {"x_m": 111_120, "y_m": 0}, {"x_m": 0, "y_m": 222_240}]


def test_air_hours_recovers_known_distance():
    # 60 nautical miles (111 120 m) at 180 kn = 1/3 h; 120 NM = 2/3 h
    h = air_hours(NODES)
    assert np.allclose([h[0, 1], h[0, 2]], [1 / 3, 2 / 3], atol=1e-3)
    assert np.allclose(h, h.T) and np.all(np.diag(h) == 0)


def test_greedy_route_stays_in_budget_and_returns_to_base():
    hours = sea_hours(NODES, sea=np.ones((2, 2)))
    S = np.array([0, 1.0, 2.0])
    r = greedy_route(NODES, S, hours, budget_h=24, dwell_h=1)
    assert r == [0, 2, 1, 0]  # highest S first
    assert greedy_route(NODES, S, hours, budget_h=1, dwell_h=1) == [0, 0]  # too tight: stay home
    assert two_opt(r, hours) == r


def test_exploration_pick_is_seeded():
    ids = [f"S{i:02d}" for i in range(4, 16)]
    assert exploration_pick(ids, seed=7) == exploration_pick(ids, seed=7)
    assert exploration_pick(ids, seed=7) in ids


def test_plans_write_both_assets_with_iso_times(tmp_path):
    out = tmp_path / "plan.json"
    ship_plan(out=out)
    aircraft_plan(out=out)
    plan = json.loads(out.read_text())
    assert set(plan) == {"ship", "aircraft"}
    for stops in plan.values():
        assert stops[0]["id"] == stops[-1]["id"] == "base"
        assert all(s["arrival_utc"].endswith("Z") and "T" in s["arrival_utc"] for s in stops)
        assert [s["arrival_utc"] for s in stops] == sorted(s["arrival_utc"] for s in stops)
