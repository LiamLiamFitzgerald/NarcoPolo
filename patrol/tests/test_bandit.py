"""Learning L5: Thompson-sampling bandit and sample-then-route (docs/learning.md)."""

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from core.schemas import check_json
from patrol import _exact, _greedy, _plan_asset, air_hours, bandit, sea_hours, two_opt
from patrol.tests.test_patrol import START, _sea, _sites
from sim.patrol import COLS

N0 = 5


def _open_sea(nodes):
    return sea_hours(nodes, _sea(np.ones((5, 400))))


def _outcomes(rows):
    """Hand-made rows in sim.patrol_outcome's shape, for exact counts; the end-to-end run with the
    real function is in test_patrol.py."""
    return pd.DataFrame(rows, columns=COLS)


def test_prior_uses_p_site_else_rank_of_S():
    st = bandit.prior(pd.DataFrame({"site_id": ["a", "b"], "p_site": [0.2, 0.6], "S": [9, 1]}), N0)
    assert st["a"]["alpha"] == pytest.approx(1.0) and st["a"]["beta"] == pytest.approx(4.0)
    assert st["b"]["alpha"] == pytest.approx(3.0) and st["b"]["last_visit_week"] is None
    # no p_site: p = rank(S) / (n + 1), ties averaged -> 1/5, 2.5/5, 2.5/5, 4/5
    st = bandit.prior(pd.DataFrame({"site_id": list("abcd"), "S": [1.0, 3.0, 3.0, 5.0]}), N0)
    assert [st[k]["alpha"] for k in "abcd"] == pytest.approx([1.0, 2.5, 2.5, 4.0])
    assert [st[k]["beta"] for k in "abcd"] == pytest.approx([4.0, 2.5, 2.5, 1.0])
    st = bandit.prior(pd.DataFrame({"site_id": ["a", "b"], "S": [2.0, 2.0]}), N0)
    assert st["a"]["alpha"] == st["a"]["beta"] == pytest.approx(2.5)  # all tied: p = 0.5
    check_json("patrol/bandit_state", st)


def test_update_counts_visits_and_leaves_unvisited_sites_alone_apart_from_discount():
    st = bandit.prior(pd.DataFrame({"site_id": ["a", "b", "c"], "p_site": [0.5, 0.5, 0.5]}), N0)
    out = _outcomes([("a", "ship", True, True), ("b", "aircraft", True, False)])
    new = bandit.update(st, out, discount=0.9, week=48)
    assert new["a"]["alpha"] == pytest.approx(0.9 * 2.5 + 1) and new["a"]["beta"] == pytest.approx(
        2.25
    )
    assert new["b"]["beta"] == pytest.approx(0.9 * 2.5 + 1) and new["b"]["alpha"] == pytest.approx(
        2.25
    )
    assert new["c"] == {
        "alpha": 2.25,
        "beta": 2.25,
        "last_visit_week": None,
    }  # unvisited: discount only
    assert new["a"]["last_visit_week"] == 48 and st["a"]["alpha"] == 2.5  # input not mutated
    assert new["b"]["last_visit_week"] == 48  # visited, found nothing: still a visit
    no_week = bandit.update(st, out, discount=0.9)
    assert all(v["last_visit_week"] is None for v in no_week.values())  # week= omitted: unchanged
    assert bandit.update(new, out, discount=1.0)["a"]["last_visit_week"] == 48
    assert bandit.update(st, _outcomes([]), discount=1.0) == st


def test_sample_is_seeded_and_in_range():
    st = bandit.prior(_sites(10, 5), N0)
    a, b = bandit.sample(st, 7), bandit.sample(st, 7)
    pd.testing.assert_series_equal(a, b)
    assert a.between(0, 1).all() and not a.equals(bandit.sample(st, 8))


def _route_hours(route, hours, dwell):
    return sum(hours[x, y] for x, y in pairwise(route)) + dwell * (len(route) - 2)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_exact_matches_greedy_when_everything_fits_and_never_scores_less(seed):
    rng = np.random.default_rng(seed)
    nodes = [{"x_m": x, "y_m": y} for x, y in rng.uniform(0, 100_000, (7, 2))]
    hours = air_hours(nodes, 12)
    S = np.array([0, *rng.uniform(0, 1, 6)])
    roomy = 1e6
    ex, gr = _exact(S, hours, roomy, 1), two_opt(_greedy([0, 0], S, hours, roomy, 1), hours)
    assert set(ex) == set(gr) == set(range(7))
    assert _route_hours(ex, hours, 1) <= _route_hours(gr, hours, 1) + 1e-9
    for budget in (6, 12, 20):  # tight budgets: exact is optimal, so never below greedy
        ex, gr = _exact(S, hours, budget, 1), _greedy([0, 0], S, hours, budget, 1)
        assert _route_hours(ex, hours, 1) <= budget
        assert S[ex].sum() >= S[gr].sum() - 1e-12


def test_exact_skips_unreachable_and_returns_home_when_nothing_fits():
    line = np.array([[abs(i - j) for j in range(4)] for i in range(4)], float)
    h = line.copy()
    h[3, :3] = h[:3, 3] = np.inf
    assert 3 not in _exact(np.array([0, 1.0, 1.0, 99.0]), h, 24, 1)
    assert _exact(np.array([0, 1.0, 1.0, 9.0]), line, 0.5, 1) == [0, 0]
    # budget 7: base-3-base is 6 h + 1 h dwell; the far high-value site beats the two near ones
    assert _exact(np.array([0, 1.0, 1.0, 9.0]), line, 7, 1) == [0, 3, 0]


def _bandit_plan(sites, state, seed, exact_max_nodes=16):
    return _plan_asset(
        sites, (0.0, 0.0), _open_sea, budget_h=6, dwell_h=1, start=START,
        theta=bandit.sample(state, seed), exploit=bandit._mean(state),
        exact_max_nodes=exact_max_nodes,
    )  # fmt: skip


def test_same_seed_and_state_give_the_same_plan_and_it_passes_the_contract():
    sites = _sites(12, 6)
    st = bandit.prior(sites, N0)
    p1, p2 = _bandit_plan(sites, st, 3), _bandit_plan(sites, st, 3)
    assert p1 == p2
    check_json("patrol/plan", {"ship": p1})
    for s in p1[1:-1]:
        assert 0 <= s["theta"] <= 1 and s["reason"] in ("exploit", "explore")
    assert "theta" not in p1[0] and not any(s.get("exploration") for s in p1)
    assert {_bandit_plan(sites, st, s)[1]["id"] for s in range(30)} != {p1[1]["id"]}  # it explores


def test_infinite_prior_strength_plans_on_p_site():
    # p_site out of step with S, so routing on S would give a different plan
    sites = _sites(10, 5).assign(p_site=[0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.6, 0.15, 0.85])
    st = bandit.prior(sites, 1e12)
    p_site = sites.set_index("site_id")["p_site"]
    pure = _plan_asset(
        sites, (0.0, 0.0), _open_sea, budget_h=6, dwell_h=1, start=START,
        theta=p_site, exploit=p_site, exact_max_nodes=16,
    )  # fmt: skip
    got = _bandit_plan(sites, st, 3)
    assert [s["id"] for s in got] == [s["id"] for s in pure]
    assert all(s["reason"] == "exploit" for s in got[1:-1])


def test_greedy_fallback_above_exact_max_nodes():
    sites = _sites(12, 6)
    st = bandit.prior(sites, N0)
    plan = _bandit_plan(sites, st, 3, exact_max_nodes=2)
    t = pd.to_datetime([s["arrival_utc"] for s in plan])
    assert (t[-1] - t[0]).total_seconds() / 3600 <= 6 and plan[0]["id"] == plan[-1]["id"] == "base"
