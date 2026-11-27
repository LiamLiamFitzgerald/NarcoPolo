"""Test-only stand-in for P1's simulator: a grid with planted rates and known exposure.

shortcut: replace with sim.simulate output once P1 lands sim/. Rates here are test numbers,
not config values.
"""

import numpy as np
import pandas as pd

from aggregate import to_coarse
from aggregate._stand_in import Observed, parent

N = 30  # 30 x 30 fine cells -> 6 x 6 coarse cells
DAYS = 120
START = pd.Timestamp("2026-07-01")
BETA = {"intercept": -2.5, "inshore": 1.5, "lane": 1.0}


def cells() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    ix, iy = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    fine = pd.DataFrame({"ix": ix.ravel(), "iy": iy.ravel()})
    fine["cell_id"] = [f"2000_{a}_{b}" for a, b in zip(fine.ix, fine.iy)]
    fine["inshore_frac"] = np.clip(
        1 - fine.iy / 12 + rng.normal(0, 0.1, len(fine)), 0, 1
    )
    fine.loc[fine.ix >= 25, "inshore_frac"] = (
        np.nan
    )  # no inshore map covers the east edge
    fine["lane"] = fine.iy.between(18, 20).astype(float)
    fine["dist_coast_m"] = 1000.0 + 800.0 * fine.iy
    fine["static_frac"] = 0.0
    fine["sea_frac"] = 1.0
    fine["level"] = 2000

    fine["parent"] = fine.cell_id.map(parent)
    agg = fine.groupby("parent").agg(
        inshore_frac=(
            "inshore_frac",
            lambda s: s.mean() if s.notna().all() else np.nan,
        ),
        lane=("lane", "mean"),  # share of lane children; P3 owns the real rule
        dist_coast_m=("dist_coast_m", "mean"),
        static_frac=("static_frac", "mean"),
        sea_frac=("sea_frac", "mean"),
    )
    coarse = agg.reset_index().rename(columns={"parent": "cell_id"}).assign(level=10000)
    return pd.concat(
        [fine.drop(columns=["ix", "iy", "parent"]), coarse], ignore_index=True
    )


def planted_rate(c: pd.DataFrame) -> pd.Series:
    """True events per unit exposure. Missing inshore map: the true value is still there, use 0.5."""
    inshore = c["inshore_frac"].fillna(0.5)
    return np.exp(
        BETA["intercept"] + BETA["inshore"] * inshore + BETA["lane"] * c["lane"]
    )


def observed(event_type: str, seed: int = 7) -> tuple[Observed, Observed, pd.DataFrame]:
    """(fine, coarse, cells). dark_small: a pass every 3rd day, a quarter of them rough (E = 0)."""
    rng = np.random.default_rng(seed)
    c = cells()
    fine = c[c.level == 2000]
    dates = pd.date_range(START, periods=DAYS)
    f = fine[["cell_id"]].merge(pd.DataFrame({"date": dates}), how="cross")
    f["event_type"] = event_type
    if event_type == "slowdown":
        f["exposure"] = 1.0
    else:
        day = (f.date - START).dt.days
        pass_day = day % 3 == 0
        rough = rng.random(DAYS)[day] < 0.25
        covered = rng.uniform(0.5, 1.0, len(f))
        f["exposure"] = np.where(pass_day & ~rough, covered, 0.0)
    rate = f.cell_id.map(planted_rate(fine).set_axis(fine.cell_id))
    f["count"] = rng.poisson(rate * f.exposure).astype(float)
    f["level"] = 2000
    fine_obs = Observed(f)
    return fine_obs, to_coarse(fine_obs), c
