"""D4 (#176): does the exact solver (_exact) beat greedy + 2-opt on simulator plans? Not a test; run with
    NARCO_DATA=<world> uv run python -m patrol.tests.exact_vs_greedy [n_draws]
on a world built by `make sim` and `make all` up to fuse. One JSON line per (asset, budget, weights): the
weights are the bandit's Thompson draws (seeds 0..n_draws-1), its posterior means, and S. Budgets are
the spec's (ship 24 h, aircraft 4 h) and half and double them, to see where a tight budget makes the
greedy ratio rule pay."""

import json
import sys
import time

import numpy as np

from core import io
from core.config import load
from patrol import (
    AIR_BUDGET_H,
    AIR_DWELL_H,
    AIR_KN,
    SHIP_BUDGET_H,
    SHIP_DWELL_H,
    SHIP_KN,
    _base,
    _exact,
    _greedy,
    _greedy_inputs,
    _sea_from_cells,
    _total,
    air_hours,
    bandit,
    sea_hours,
    two_opt,
)


def _greedy_2opt(S, hours, budget_h, dwell_h):
    return two_opt(_greedy([0, 0], S, hours, budget_h, dwell_h), hours)


def _timed(f, *args):
    t = time.perf_counter()
    r = f(*args)
    return r, time.perf_counter() - t


def main(n_draws: int = 20) -> None:
    cfg, _ = load(io.CONFIG_PATH)
    sites = io.read_stage("fuse/sites")
    cand = _greedy_inputs(sites).reset_index(drop=True)
    base, _ = _base(cfg)
    nodes = [
        {"x_m": base[0], "y_m": base[1]},
        *({"x_m": r.x_m, "y_m": r.y_m} for r in cand.itertuples()),
    ]
    sea = _sea_from_cells(io.read_stage("reference/cells"))
    state = bandit.prior(cand, cfg["learn"]["prior_strength"])
    ids = cand["site_id"]
    weights = {f"theta{k}": bandit.sample(state, k).loc[ids].to_numpy() for k in range(n_draws)}
    weights["mean"] = bandit._mean(state).loc[ids].to_numpy()
    weights["S"] = cand["S"].to_numpy()
    assets = {
        "ship": (sea_hours(nodes, sea, SHIP_KN), SHIP_BUDGET_H, SHIP_DWELL_H),
        "aircraft": (air_hours(nodes, AIR_KN), AIR_BUDGET_H, AIR_DWELL_H),
    }
    for asset, (hours, budget, dwell) in assets.items():
        for b in (budget / 2, budget, budget * 2):
            for name, w in weights.items():
                S = np.array([0.0, *w])
                ex, t_ex = _timed(_exact, S, hours, b, dwell)
                gr, t_gr = _timed(_greedy_2opt, S, hours, b, dwell)
                row = {
                    "asset": asset, "budget_h": b, "weights": name, "n_sites": len(cand),
                    "v_exact": float(S[ex].sum()), "v_greedy": float(S[gr].sum()),
                    "h_exact": _total(ex, hours, dwell), "h_greedy": _total(gr, hours, dwell),
                    "t_exact_s": t_ex, "t_greedy_s": t_gr,
                    "same_set": set(ex) == set(gr), "same_route": ex in (gr, gr[::-1]),
                }  # fmt: skip
                print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
