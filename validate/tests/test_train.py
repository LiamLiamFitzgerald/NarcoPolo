"""L4 fitting (docs/learning.md): rung 1 weights >= 0 and monotone, the NAM is monotone, no look-ahead,
the model JSON round-trips, and the same inputs give the same model. Stand-ins for #150 (regimes) and #153
(agent scores) until they are on integration."""

import inspect
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from core import io
from core.config import load
from core.split import Split
from validate import train

FEATURES = ["oe", "midp", "gi", "cusum"]
P = train._params(load(io.CONFIG_PATH)[0])
K = 15


def _season(
    seed: int, n_cells: int = 200, n_weeks: int = 17, coef=(1.0, 1.5, 0.8, -0.5)
) -> pd.DataFrame:
    """Stand-in site-weeks: label ~ Bernoulli(sigmoid(-4 + coef . x)); the last coefficient is negative, so the
    non-negative stack must clip it to 0."""
    rng = np.random.default_rng(seed)
    start = date(2026, 8, 2)  # a Sunday
    d = pd.to_datetime([start + timedelta(weeks=w) for w in range(n_weeks)])
    rows = pd.DataFrame(
        {
            "cell_id": np.tile([f"2000_{i}_0" for i in range(n_cells)], n_weeks),
            "date": np.repeat(d, n_cells),
        }
    )
    X = rng.normal(size=(len(rows), 4))
    rows[FEATURES] = X
    rows["midp"] = np.abs(rows["midp"])
    z = -4 + rows[FEATURES].to_numpy() @ np.array(coef)
    rows["label"] = rng.random(len(rows)) < 1 / (1 + np.exp(-z))
    return rows


SPLIT = Split(date(2026, 10, 10), 7, 7)


def _frames(seeds):
    return [(_season(s), SPLIT) for s in seeds]


def test_stack_weights_nonnegative_and_monotone():
    rows = train._train(_season(0), SPLIT)
    X, y = rows[FEATURES].to_numpy(float), rows["label"].to_numpy(float)
    fit = train._fit(1, X, y, P, 0)
    assert (fit["w"] >= 0).all()
    assert fit["w"][3] == 0  # the negative-effect agent is clipped, not used backwards
    assert fit["w"][1] > 0  # the strongest agent is used
    base = train._predict(fit, X, X[:, 1])
    for j in range(4):
        up = X.copy()
        up[:, j] += 1.0
        assert (train._predict(fit, up, up[:, 1]) >= base - 1e-12).all()


def test_nam_is_monotone_in_every_score():
    rows = train._train(_season(1), SPLIT)
    X, y = rows[FEATURES].to_numpy(float), rows["label"].to_numpy(float)
    fit = train._fit(2, X, y, {**P, "nam_epochs": 50}, 0)
    assert (fit["u"] >= 0).all() and (fit["a"] >= 0).all()
    base = train._predict(fit, X, X[:, 1])
    for j in range(4):
        up = X.copy()
        up[:, j] += 0.5
        assert (train._predict(fit, up, up[:, 1]) >= base - 1e-12).all()


def test_labels_after_the_cutoff_do_not_change_the_model():
    frames = _frames([2, 3])
    held = _frames([4, 5])
    shuffled = []
    rng = np.random.default_rng(0)
    for rows, split in frames:
        late = pd.to_datetime(rows["date"]) >= pd.Timestamp(split.cutoff)
        r = rows.copy()
        r.loc[late, "label"] = rng.permutation(r.loc[late, "label"].to_numpy())
        shuffled.append((r, split))
    p = {**P, "nam_epochs": 20}
    a = train._ladder(frames, held, FEATURES, p, K, seed=0)
    b = train._ladder(shuffled, held, FEATURES, p, K, seed=0)
    assert a["weights"] == b["weights"] and a["intercept"] == b["intercept"]
    assert a["metrics"]["n_positive"] == b["metrics"]["n_positive"]


def test_training_rows_after_the_cutoff_raise():
    rows = _season(0)
    with pytest.raises(ValueError, match="look-ahead"):
        SPLIT.assert_train(rows)  # what _train guards against
    assert pd.to_datetime(train._train(rows, SPLIT)["date"]).max() < pd.Timestamp(SPLIT.cutoff)


def test_scored_rows_start_after_the_embargo():
    s = train._scored(_season(0), SPLIT)
    assert pd.to_datetime(s["date"]).min() >= pd.Timestamp(SPLIT.cutoff + timedelta(days=7))


def test_ladder_is_deterministic_and_gates_rung_2_on_n_eff():
    p = {**P, "nam_epochs": 20}
    frames, held = _frames([6, 7]), _frames([8, 9])
    a = train._ladder(frames, held, FEATURES, p, K, seed=0)
    assert a == train._ladder(frames, held, FEATURES, p, K, seed=0)
    assert a["metrics"]["n_eff"] >= 500 and a["metrics"]["rungs_tried"] == [1, 2]
    small = train._ladder(frames, held, FEATURES, {**p, "n_eff_min": 10**9}, K, seed=0)
    assert small["metrics"]["rungs_tried"] == [1]


def test_promotion_needs_a_gain_beyond_two_standard_errors_and_no_worse_brier():
    cur = {"precision_at_k": [0.1, 0.1, 0.1], "brier": [0.1]}
    assert train._promote({"precision_at_k": [0.2, 0.21, 0.19], "brier": [0.1]}, cur, 2)["promoted"]
    assert not train._promote({"precision_at_k": [0.2, 0.0, 0.3], "brier": [0.1]}, cur, 2)[
        "promoted"
    ]
    assert not train._promote({"precision_at_k": [0.2, 0.21, 0.19], "brier": [0.2]}, cur, 2)[
        "promoted"
    ]
    assert not train._promote(
        {"precision_at_k": [0.2], "brier": [0.1]}, {**cur, "precision_at_k": [0.1]}, 2
    )["promoted"]  # one season: no standard error, no promotion


def test_midp_matches_poisson_at_integers_and_interpolates_soft_counts():
    mu = np.array([2.0, 2.0, 2.0])
    c = np.array([3.0, 4.0, 3.5])
    p = 10 ** -train._midp(c, mu)
    exact = poisson.sf(c[:2], mu[:2]) + 0.5 * poisson.pmf(c[:2], mu[:2])
    assert np.allclose(p[:2], exact) and np.isclose(p[2], exact.mean())


def test_scores_skip_unobserved_rows_and_cusum_only_looks_back():
    days = pd.to_datetime(
        [date(2026, 8, 3) + timedelta(days=i) for i in range(21)]
    )  # 3 Mon-Sun weeks
    cells = ["2000_0_0", "2000_1_0", "2000_5_5"]
    obs = pd.DataFrame(
        [(c, 2000, d, "slowdown", 0.0, 1.0) for c in cells for d in days],
        columns=["cell_id", "level", "date", "event_type", "count", "exposure"],
    )
    obs.loc[(obs["cell_id"] == "2000_5_5") & (obs["date"] < days[7]), "exposure"] = (
        0.0  # week 1 unseen
    )
    obs.loc[(obs["cell_id"] == "2000_0_0") & (obs["date"] == days[16]), "count"] = (
        5.0  # week 3 burst
    )
    exp = obs[["cell_id", "date", "event_type"]].assign(mu=0.1, fold=pd.NA)
    s = train._scores(obs, exp)
    assert len(s[s["cell_id"] == "2000_5_5"]) == 2  # no row for the unseen week, not a zero
    hot = s[s["cell_id"] == "2000_0_0"].sort_values("date")
    assert (
        hot["cusum"].iloc[:2].eq(0).all() and hot["cusum"].iloc[2] > 0
    )  # burst counts only from its week
    last = s[s["date"] == s["date"].max()].set_index("cell_id")
    assert last["gi"].idxmax() == "2000_0_0" and last["oe"].idxmax() == "2000_0_0"


# ---------------------------------------------------------------- on the simulator


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    """fit_site_model on 2 seeds; `pass_aware` is a stand-in for #150 (the fixed simulator, other seeds)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("m") / "data"))
    real = train._simulate

    def stand_in(cfg, seed, regime):
        real(cfg, seed + (100 if regime != "fixed" else 0), "fixed")

    mp.setattr(train, "_simulate", stand_in)
    model = train.fit_site_model({"train": ["fixed"], "held_out": ["pass_aware"]}, [1, 2])
    yield model, train.model_path()
    mp.undo()


def test_model_json_round_trips_and_has_the_contract_keys(fitted):
    model, path = fitted
    assert json.loads(path.read_text()) == model
    for key in (
        "rung",
        "features",
        "weights",
        "intercept",
        "config_hash",
        "metrics",
        "seeds",
        "regimes",
    ):
        assert key in model
    assert model["config_hash"] == load(io.CONFIG_PATH)[1]
    assert model["seeds"] == [1, 2] and model["regimes"]["held_out"] == ["pass_aware"]
    assert model["metrics"]["rungs_tried"] == [1]  # 2 seeds: n_eff < 500, stop at rung 1
    assert "lightgbm" in model["metrics"]


def test_stack_ranks_the_planted_site_in_the_top_k_on_fixed():
    """Rung 1 fitted on one fixed season, applied to another: the planted site is in the weekly top k."""
    cfg = load(io.CONFIG_PATH)[0]
    fit_rows, fit_split = train._site_weeks(cfg, "fixed", 1)
    rows, split = train._site_weeks(cfg, "fixed", 3)
    tr = train._train(fit_rows, fit_split)
    fit = train._fit(1, tr[FEATURES].to_numpy(float), tr["label"].to_numpy(float), P, 0)
    s = train._scored(rows, split)
    s = s.assign(p=train._predict(fit, s[FEATURES].to_numpy(float), s["midp"].to_numpy(float)))
    rank = s.groupby("date")["p"].rank(ascending=False, method="first")
    assert s["label"].any() and (rank[s["label"]] <= K).all()


def test_real_regimes_once_l1_is_on_integration(tmp_path, monkeypatch):
    from sim.simulate import simulate

    if "regime" not in inspect.signature(simulate).parameters:
        pytest.skip("sim.simulate has no regime argument yet (#150)")
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    model = train.fit_site_model({"train": ["fixed", "two_sites"], "held_out": ["pass_aware"]}, [1])
    assert model["rung"] in (0, 1)
