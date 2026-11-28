"""Drop regimes for the learning layer (docs/learning.md L1). A regime changes only where and when drops happen.

`fixed` draws nothing here, so its output is exactly what it was before regimes existed.
"""

import numpy as np
import pandas as pd

from core.config import Config
from core.grid import FINE

REGIMES = ("fixed", "two_sites", "pass_aware", "displacing", "null")


def _near(fine: pd.DataFrame, ok: np.ndarray, cell: int, km: float) -> np.ndarray:
    """Candidate site cells other than `cell` whose centre is within `km` of its centre."""
    ix, iy = fine["ix"].to_numpy(), fine["iy"].to_numpy()
    d_km = np.hypot(ix - ix[cell], iy - iy[cell]) * FINE / 1000
    return np.flatnonzero(ok & (d_km <= km) & (np.arange(len(fine)) != cell))


def _gap_time(
    day: int, pass_days: np.ndarray, buf_d: float, days: int, rr: np.random.Generator
) -> float:
    """A time on `day` (or the next day that has one) at least `buf_d` days from every pass, uniform over the gaps."""
    for d in range(day, days):
        lo, hi = float(d), float(d + 1)
        t, gaps = lo, []
        for p in np.sort(pass_days[(pass_days + buf_d > lo) & (pass_days - buf_d < hi)]):
            if p - buf_d > t:
                gaps.append((t, p - buf_d))
            t = max(t, p + buf_d)
        if t < hi:
            gaps.append((t, hi))
        if gaps:
            w = np.array([b - a for a, b in gaps])
            a, b = gaps[int(rr.choice(len(gaps), p=w / w.sum()))]
            return float(rr.uniform(a, b))
    return float("nan")  # no gap left in the season


def plant(
    cfg: Config,
    regime: str,
    drop_days: list[float],
    site: int,
    ok: np.ndarray,
    fine: pd.DataFrame,
    pass_days: np.ndarray,
    days: int,
    rr: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(drop days, drop cells, visit days, visit cells); days are floats since day 0, cells index `fine`.

    `drop_days` is the fixed regime's schedule (one drop about every `sim.drop_interval_days`); every regime keeps
    its cadence. Visits are the simulator's own patrol, used only by `displacing`.
    """
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}; expected one of {REGIMES}")
    lc = cfg["learn"]
    dd = np.asarray(drop_days, float)
    cells = np.full(len(dd), site, int)
    none_f, none_i = np.array([], float), np.array([], int)
    if regime == "null":
        return none_f, none_i, none_f, none_i
    if (
        regime == "two_sites"
    ):  # first half at `site`, second half somewhere else (not a displaced neighbour)
        near = _near(fine, ok, site, lc["displace_km"])
        far = np.setdiff1d(np.flatnonzero(ok), np.append(near, site))
        cells[dd >= days / 2] = int(rr.choice(far))
    elif regime == "pass_aware":  # the adversary knows the public pass schedule
        dd = np.array(
            [_gap_time(int(d), pass_days, lc["pass_buffer_h"] / 24, days, rr) for d in dd]
        )
        keep = ~np.isnan(dd)
        dd, cells = dd[keep], cells[keep]
    elif (
        regime == "displacing"
    ):  # after a visit to the active site, the next drops move to a neighbour
        every = float(lc["displace_visit_days"])
        visits = np.arange(every, days, every) + 0.5  # noon
        vcells, cur, v = [], site, 0
        for i, d in enumerate(dd):
            while v < len(visits) and visits[v] < d:
                vcells.append(cur)
                nb = _near(fine, ok, cur, lc["displace_km"])
                cur = int(rr.choice(nb)) if len(nb) else cur
                v += 1
            cells[i] = cur
        vcells += [cur] * (len(visits) - v)  # visits after the last drop: nothing left to move
        return dd, cells, visits, np.asarray(vcells, int)
    return dd, cells, none_f, none_i
