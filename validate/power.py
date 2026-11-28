"""#351 power diagnostic: which cells can ever flag a small-boat surprise over the evaluation window.

The test is one cell against its own forecast (the baseline is given, not estimated), so the power is the exact
upper tail, not the two-sample `power_poisson_ratio_2indep`: under normal, a cell's window total X has mean
M = sum of mu over its observed cell-days and variance phi * M (negative binomial, Poisson when phi <= 1, as in
forecast's intervals). It flags when P(X >= x) <= alpha; power is P(flag) when the true rate is ratio * M.
Unobserved cells (no cell-day with exposure > 0) get NaN, never 0 power (principle 4).
"""

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from core import io
from core.config import load
from core.expected import KEY, scoring_rows


def _sf(x: np.ndarray, mean: np.ndarray | float, phi: np.ndarray | float) -> np.ndarray:
    """P(X >= x), X with this mean and variance phi * mean."""
    x, mean, phi = np.broadcast_arrays(*(np.asarray(a, float) for a in (x, mean, phi)))
    out = stats.poisson.sf(x - 1, mean)
    nb = phi > 1
    out[nb] = stats.nbinom.sf(x[nb] - 1, mean[nb] / (phi[nb] - 1), 1 / phi[nb])
    return out


def _power(M: np.ndarray, phi: np.ndarray, ratio: float, alpha: float) -> np.ndarray:
    """Exact power of the one-sided window-total test at level alpha; NaN where M is NaN or 0."""
    M, phi = np.broadcast_arrays(np.asarray(M, float), np.asarray(phi, float))
    out = np.full(M.shape, np.nan)
    ok = np.isfinite(M) & (M > 0)
    m, f = M[ok], phi[ok]
    # smallest x with P(X >= x) <= alpha: search upward from the median, bounded well past the tail
    hi = np.ceil(m + 40 * np.sqrt(np.maximum(f, 1) * m) + 40).astype(int)
    tails = [_sf(np.arange(h + 1), mi, fi) <= alpha for mi, fi, h in zip(m, f, hi, strict=True)]
    if not all(t.any() for t in tails):
        raise ValueError("power: critical count not found within the search bound")
    crit = np.array([np.argmax(t) for t in tails])
    out[ok] = _sf(crit, ratio * m, f)
    return out


def _window(dates: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Global settings: Monday of the ISO week three weeks before T's week, up to T (T = the last forecast day)."""
    T = pd.Timestamp(dates.max())
    return T - timedelta(days=T.weekday() + 21), T


def _power_table(
    expected: pd.DataFrame, observed: pd.DataFrame, alpha: float, ratios: list[float]
) -> pd.DataFrame:
    """Per 2 km cell: observed cell-days in the window, expected small-boat detections per cell-day, phi, and the
    power to flag each rate ratio. Cells with no observed cell-day have NaN mu and power."""
    e = scoring_rows(expected[expected["event_type"] == "dark_small"])
    if "fold" in e:
        e = e[e["fold"] == 0]  # live forecast = the evaluation window
    lo, hi = _window(e["date"])
    o = observed[(observed["event_type"] == "dark_small") & (observed["level"] == 2000)]
    o = o[(o["date"] >= lo) & (o["date"] <= hi)]
    m = o.merge(e[KEY + ["mu", "phi"]], on=KEY, how="left")
    seen = m[(m["exposure"] > 0) & m["mu"].notna()]
    g = seen.groupby("cell_id")
    t = pd.DataFrame({"cell_id": sorted(o["cell_id"].unique())}).set_index("cell_id")
    t["cell_days"] = g.size().reindex(t.index).fillna(0).astype(int)
    t["mu_per_day"] = g["mu"].mean().reindex(t.index)
    t["mu_window"] = g["mu"].sum().reindex(t.index).where(t["cell_days"] > 0)
    t["phi"] = g["phi"].mean().reindex(t.index)
    for r in ratios:
        t[f"power_rr{r:g}"] = _power(t["mu_window"].to_numpy(), t["phi"].to_numpy(), r, alpha)
    return t.reset_index()


def _power_block() -> dict[str, Any]:
    """reports/validation.json `power`: the per-cell table and the share of observed cells with power >= threshold."""
    v = load(io.CONFIG_PATH)[0]["validate"]
    ratios = [float(r) for r in v["power_rate_ratios"]]
    table = _power_table(
        io.read_stage("forecast/expected"),
        io.read_stage("aggregate/observed"),
        float(v["power_alpha"]),
        ratios,
    )
    seen = table["mu_window"].notna()
    share = {
        f"rr{r:g}": float((table.loc[seen, f"power_rr{r:g}"] >= v["power_min"]).mean())
        if seen.any()
        else None
        for r in ratios
    }
    # comparison runs: sim.baseline_rate boats per cell-day seen with each detection probability, over the
    # median number of observed cell-days per cell
    sim = load(io.CONFIG_PATH)[0]["sim"]
    days = float(table.loc[seen, "cell_days"].median()) if seen.any() else float("nan")
    scenarios = [
        {
            "p_detect": p,
            "mu_window": sim["baseline_rate"] * p * days,
            **{
                f"power_rr{r:g}": float(
                    _power(
                        np.array([sim["baseline_rate"] * p * days]),
                        np.array([1.0]),
                        r,
                        float(v["power_alpha"]),
                    )[0]
                )
                for r in ratios
            },
        }
        for p in sim["p_detect_scenarios"]
    ]
    return {
        "scenarios": scenarios,
        "alpha": v["power_alpha"],
        "power_min": v["power_min"],
        "n_cells": len(table),
        "n_observed_cells": int(seen.sum()),
        "share_with_power_at_least_min": share,  # over observed cells only
        "cells": table,
    }
