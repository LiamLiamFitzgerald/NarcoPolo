"""Thompson-sampling bandit over drop sites (docs/learning.md L5).

State: {site_id: {alpha, beta, last_visit_week}}, a Beta posterior on "a visit here finds something".
Only visited sites learn; an unvisited site is never "found nothing" (learning principle 3)."""

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

State = dict[str, dict[str, Any]]

_EPS = 1e-6  # keeps alpha0, beta0 > 0 when p is exactly 0 or 1 (a Beta needs both positive)


def prior(sites: pd.DataFrame, n0: float) -> State:
    """Beta(n0 * p, n0 * (1 - p)) per site, n0 = learn.prior_strength virtual visits.
    p = p_site when the column exists, else S rescaled to 0-1 over these sites (issue 151)."""
    if "p_site" in sites:
        p = sites["p_site"].astype(float)
    else:
        s = sites["S"].astype(float)
        span = s.max() - s.min()
        p = (s - s.min()) / span if span > 0 else pd.Series(0.5, index=s.index)
    p = p.clip(_EPS, 1 - _EPS)
    return {
        str(i): {"alpha": float(n0 * q), "beta": float(n0 * (1 - q)), "last_visit_week": None}
        for i, q in zip(sites["site_id"], p, strict=True)
    }


def update(
    state: Mapping[str, Mapping[str, Any]],
    outcomes: pd.DataFrame,
    discount: float,
    week: int | None = None,
) -> State:
    """Discount every site (alpha, beta <- discount * alpha, beta), then one count per visit row of
    outcomes [site_id, asset, visited, found]: found -> alpha + 1, visited and not found -> beta + 1.
    Sites with no visit row change only by the discount. `week`, if given, becomes last_visit_week."""
    new = {
        k: {**v, "alpha": discount * v["alpha"], "beta": discount * v["beta"]}
        for k, v in state.items()
    }
    for r in outcomes[outcomes["visited"].astype(bool)].itertuples():
        st = new.get(str(r.site_id))
        if st is None:  # visited a site the bandit never offered: no prior to update
            continue
        st["alpha" if r.found else "beta"] += 1
        if week is not None:
            st["last_visit_week"] = int(week)
    return new


def sample(state: Mapping[str, Mapping[str, Any]], seed: int) -> pd.Series:
    """theta_s ~ Beta(alpha_s, beta_s) per site, seeded, in sorted site order so the draw is repeatable."""
    ids = sorted(state)
    rng = np.random.default_rng(seed)
    a = np.array([state[i]["alpha"] for i in ids], float)
    b = np.array([state[i]["beta"] for i in ids], float)
    return pd.Series(rng.beta(a, b), index=pd.Index(ids, name="site_id"), name="theta")


def _mean(state: Mapping[str, Mapping[str, Any]]) -> pd.Series:
    """Posterior mean alpha / (alpha + beta): the pure-exploit weights behind the 'exploit' reason."""
    ids = sorted(state)
    return pd.Series(
        [state[i]["alpha"] / (state[i]["alpha"] + state[i]["beta"]) for i in ids],
        index=pd.Index(ids, name="site_id"),
        name="mean",
    )
