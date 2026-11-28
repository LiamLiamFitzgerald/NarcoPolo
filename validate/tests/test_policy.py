"""L6 policy evaluation on small stand-ins (a tiny site table, a fake patrol_outcome, a fake bandit).
The end-to-end test against sim/patrol/fuse is skipped until #150, #151 and #152 land."""

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from validate import policy
from validate.policy import POLICIES, _block, _Deps, _entropy, _evaluate, _Season

SITES = pd.DataFrame(
    {
        "site_id": [f"s{i}" for i in range(6)],
        "S": [0.9, 0.8, 0.3, 0.2, 0.1, 0.05],  # the active site s1 is in fixed_S's top 2
        "p_site": [0.6, 0.7, 0.2, 0.2, 0.1, 0.1],
    }
)
WEEKS = list(pd.date_range("2026-01-04", periods=8, freq="7D"))
K = 2  # stops per plan in the stand-in route


def _world(regime: str, seed: int) -> _Season:
    """`fixed`-like: one drop at s1 two days after every cutoff; `null`-like: no drops."""
    times = (
        [w.tz_localize("UTC") + pd.Timedelta(days=2) for w in WEEKS] if regime == "fixed" else []
    )
    truth = pd.DataFrame(
        {"kind": "drop", "site_id": "s1", "time_utc": pd.to_datetime(times, utc=True)}
    )

    def route(cands, weights, cutoff):
        top = cands["site_id"].to_numpy()[np.argsort(-np.asarray(weights), kind="stable")[:K]]
        return {"ship": [{"id": "base"}, *({"id": s} for s in top), {"id": "base"}]}, 2.0 * K

    return _Season(truth=truth, weeks=WEEKS, sites_at=lambda c: SITES, route=route)


def _outcome(truth, plan, week):
    """Rows for visited stops only; found = a drop at that site in the week after the cutoff."""
    ids = [s["id"] for stops in plan.values() for s in stops if s["id"] != "base"]
    t = truth["time_utc"]
    c = week.tz_localize("UTC")
    hit = set(truth.loc[(t > c) & (t <= c + pd.Timedelta(days=7)), "site_id"])
    return pd.DataFrame(
        {"site_id": ids, "asset": "ship", "visited": True, "found": [i in hit for i in ids]}
    )


def _prior(sites, n0):
    return {
        r.site_id: {"alpha": n0 * r.p_site, "beta": n0 * (1 - r.p_site)} for r in sites.itertuples()
    }


def _update(state, out, discount):
    new = {
        k: {"alpha": discount * v["alpha"], "beta": discount * v["beta"]} for k, v in state.items()
    }
    for r in out[out["visited"]].itertuples():
        new[r.site_id]["alpha" if r.found else "beta"] += 1
    return new


def _sample(state, seed):
    rng = np.random.default_rng(seed)
    return pd.Series({k: rng.beta(v["alpha"], v["beta"]) for k, v in sorted(state.items())})


DEPS = _Deps(
    world=_world,
    outcome=_outcome,
    bandit=SimpleNamespace(prior=_prior, update=_update, sample=_sample),
)


@pytest.fixture(scope="module")
def fixed():
    return _evaluate(POLICIES, "fixed", range(5), DEPS).set_index(["policy", "seed"])


def test_oracle_regret_is_zero_and_it_finds_every_week(fixed):
    o = fixed.loc["oracle"]
    assert (o["regret"] == 0).all()
    assert (o["weeks_to_first_find"] == 1).all()
    assert o["finds_per_patrol_hour"].eq(len(WEEKS) / (len(WEEKS) * 2.0 * K)).all()


def test_random_is_worst_on_fixed(fixed):
    mean = fixed.groupby("policy")["regret"].mean()
    assert mean.idxmax() == "random"
    assert mean["random"] > 0


def test_null_has_no_finds_and_no_regret():
    f = _evaluate(POLICIES, "null", range(3), DEPS)
    assert (f["regret"] == 0).all()
    assert f["finds_per_patrol_hour"].eq(0).all()
    assert f["weeks_to_first_find"].isna().all()


def test_coverage_entropy_is_max_when_visits_are_uniform():
    assert math.isclose(_entropy(pd.Series([3, 3, 3, 3])), math.log(4))
    assert _entropy(pd.Series([9, 1, 1, 1])) < math.log(4)
    assert math.isnan(_entropy(pd.Series([], dtype=float)))


def test_same_seed_same_results():
    a = _evaluate(["bandit", "random"], "fixed", [7], DEPS)
    b = _evaluate(["bandit", "random"], "fixed", [7], DEPS)
    pd.testing.assert_frame_equal(a, b)


def test_columns_and_unknown_policy():
    f = _evaluate(["fixed_S"], "fixed", [0], DEPS)
    assert list(f.columns) == policy.COLUMNS
    with pytest.raises(ValueError):
        _evaluate(["oops"], "fixed", [0], DEPS)


def test_block_splits_train_and_held_out(monkeypatch):
    learn = {"regimes": {"train": ["fixed"], "held_out": ["null"]}, "n_seeds": 2,
             "prior_strength": 5, "discount": 0.9}  # fmt: skip
    monkeypatch.setattr(policy, "load", lambda _: ({"learn": learn}, ""))
    b = _block(DEPS)
    assert b is not None
    assert {r["regime"] for r in b["train"]} == {"fixed"}
    assert {r["regime"] for r in b["held_out"]} == {"null"}
    assert all(r["n_seeds"] == 2 for r in b["train"])


def test_block_is_none_while_dependencies_are_missing(monkeypatch):
    monkeypatch.setattr(policy, "_real_deps", lambda: None)
    assert _block() is None


def test_end_to_end_on_the_simulator():
    if policy._real_deps() is None:
        pytest.skip("needs sim.patrol_outcome (#150), patrol.bandit (#151), fuse.learn (#152)")
    f = policy.evaluate("oracle", "fixed", [0])
    assert list(f.columns) == policy.COLUMNS
    assert (f["regret"] == 0).all()
