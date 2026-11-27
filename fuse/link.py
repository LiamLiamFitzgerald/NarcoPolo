"""Lag link (issue 56), drop sites, significance, recurrence, piers and reasons. The sites, permutation,
recurrence, pier and reason steps are still STUBS (issue 24) returning neutral, schema-valid placeholders."""

from typing import NamedTuple

import numpy as np
import pandas as pd

from core import io
from core.grid import FINE, neighbours
from fuse._common import PARAMS, RADAR_HISTORY_DAYS, _provenance

_SITE_COLUMNS = {
    "site_id": str, "x_m": float, "y_m": float, "n_slowdowns": int, "S": float, "p_perm": float,
    "bh_flag": bool, "recurrence": int, "followup_unobserved": int, "agreement": int, "reasons": object,
    "top_piers": object,
}  # fmt: skip
_CELL_COLUMNS = {
    "cell_id": str, "date": object, "event_type": str, "p_mid": float, "bh_flag": bool, "gi_z": float,
    "cusum_s": float, "context": float, "U": float, "y": float, "y_week": float, "agreement": int,
}  # fmt: skip


def _days(values) -> pd.DatetimeIndex:
    """UTC calendar days as naive midnight timestamps, from dates, datetime64 or tz-aware times."""
    t = pd.to_datetime(pd.Series(list(values)))
    if t.dt.tz is not None:
        t = t.dt.tz_convert("UTC").dt.tz_localize(None)
    return pd.DatetimeIndex(t.dt.normalize())


def _small_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["event_type"] == "dark_small"].assign(date=lambda f: _days(f["date"]))


def _exposure(observed: pd.DataFrame) -> pd.Series:
    """dark_small exposure E per fine (cell_id, date), unobserved rows included as E = 0."""
    f = _small_rows(observed[observed["level"] == FINE])
    return f.set_index(["cell_id", "date"])["exposure"]


def _u_small(cells: pd.DataFrame, observed: pd.DataFrame) -> pd.Series:
    """dark_small U per observed (cell_id, date), set to 0 where C = 0 (A5): tied ranks of quiet cell-days must
    not hand every slowdown a link score. Unobserved cell-days have no row (fuse/cells holds E > 0 only)."""
    count = _small_rows(observed[observed["level"] == FINE])[["cell_id", "date", "count"]]
    u = _small_rows(cells)[["cell_id", "date", "U"]].merge(
        count, on=["cell_id", "date"], how="left"
    )
    u["U"] = u["U"].where(u["count"] > 0, 0.0)
    return u.set_index(["cell_id", "date"])["U"]


def _window(s, series: pd.Series, nbrs, days) -> tuple[np.ndarray, pd.Timestamp]:
    """Rows of `series` in N x [date, date + days]; N = s's cell and its neighbours within link_radius_m."""
    d = _days([s["date"]])[0]
    cell, date = (
        series.index.get_level_values(0),
        pd.DatetimeIndex(series.index.get_level_values(1)),
    )
    N = [s["cell_id"], *nbrs.get(s["cell_id"], [])]
    return cell.isin(N) & (date >= d) & (date <= d + pd.Timedelta(days=days)), d


def followup_exposure(s, exposure, nbrs, days=PARAMS["link_days"]) -> float:
    """X = sum of dark_small exposure over N x [date, date + days] (issue 3: same-day pick-ups count).
    s: mapping with cell_id and date; exposure: Series on (cell_id, date); nbrs: cell -> cells within 4 km."""
    m, _ = _window(s, exposure, nbrs, days)
    return float(exposure[m].sum())


def link_score(s, U_small, nbrs, tau=PARAMS["tau_days"]) -> float | None:
    """L = U_slowdown(s) x max over N x window of U_small(c, t) e^(-(t - date) / tau), lags in whole days (the
    slowdown is at 12:00 of its date, a cell-day at 12:00 of its own). U_small holds observed rows only, so no
    row in the window means X = 0: None, never 0. s: mapping with cell_id, date and U (the slowdown type's)."""
    m, d = _window(s, U_small, nbrs, PARAMS["link_days"])
    if not m.any():
        return None
    lag = (pd.DatetimeIndex(U_small.index.get_level_values(1)[m]) - d).days.to_numpy()
    return float(s["U"] * np.max(U_small[m].to_numpy() * np.exp(-lag / tau)))


def sites(slowdowns: pd.DataFrame) -> pd.DataFrame:  # stub, issue 24: one site per 2 km cell (A2)
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in _SITE_COLUMNS.items()})


def suppress(ranked_sites: pd.DataFrame, radius_m=PARAMS["link_radius_m"]) -> pd.DataFrame:
    return ranked_sites  # stub, issue 24


def site_score(L, ages, half_life=PARAMS["half_life_days"]) -> float:  # stub, issue 24
    return 0.0


class LinkTable(NamedTuple):
    """best[c, d] = max decayed U_small and X[c, d] = follow-up exposure for a slowdown in cell c on day0 + d.
    Days run from (first radar day - link_days) to the last radar day: exactly the slowdowns whose window
    overlaps the radar history. best is -inf where the window holds no observed small-boat row."""

    cells: pd.Index
    day0: pd.Timestamp
    best: np.ndarray
    X: np.ndarray


def link_table(
    U_small, exposure, nbrs, days=PARAMS["link_days"], tau=PARAMS["tau_days"]
) -> LinkTable:
    """Precompute best decayed U_small and X for every (cell, date) in the 4 km neighbourhood (A4), so a
    permutation shuffle is a lookup. Same inputs and formula as followup_exposure and link_score."""
    cells = pd.Index(
        sorted(
            set(nbrs)
            | {n for v in nbrs.values() for n in v}
            | set(exposure.index.get_level_values(0))
        )
    )
    dates = pd.DatetimeIndex(exposure.index.get_level_values(1)).append(
        pd.DatetimeIndex(U_small.index.get_level_values(1))
    )
    day0 = dates.min() - pd.Timedelta(days=days)
    n_d = (dates.max() - day0).days + 1

    def dense(series: pd.Series, fill: float) -> np.ndarray:
        a = np.full((len(cells), n_d + days), fill)
        di = (pd.DatetimeIndex(series.index.get_level_values(1)) - day0).days
        a[cells.get_indexer(series.index.get_level_values(0)), di] = series.to_numpy(float)
        return a

    E, U = dense(exposure, 0.0), dense(U_small, -np.inf)
    N = [cells.get_indexer(pd.Index([c, *nbrs.get(c, [])])) for c in cells]
    M = np.stack([U[ix].max(axis=0) for ix in N])  # best U in N per day
    EN = np.stack([E[ix].sum(axis=0) for ix in N])
    best = np.max([M[:, k : k + n_d] * np.exp(-k / tau) for k in range(days + 1)], axis=0)
    X = np.sum([EN[:, k : k + n_d] for k in range(days + 1)], axis=0)
    return LinkTable(cells, day0, best, X)


def _lookup(table: LinkTable, cell_ids, dates) -> tuple[np.ndarray, np.ndarray]:
    """(best, X) per slowdown; NaN for both where its window misses the radar history."""
    ci = table.cells.get_indexer(pd.Index(cell_ids))
    di = (_days(dates) - table.day0).days.to_numpy()
    ok = (ci >= 0) & (di >= 0) & (di < table.X.shape[1])
    best, X = np.full(len(ci), np.nan), np.full(len(ci), np.nan)
    best[ok], X[ok] = table.best[ci[ok], di[ok]], table.X[ci[ok], di[ok]]
    return best, X


def _radar(series: pd.Series, T) -> pd.Series:
    """Rows of a (cell_id, date) series in the radar history T - 89 .. T, so the link table's days are exactly
    the slowdowns whose window overlaps it (older E = 0 rows would otherwise read as follow-up unobserved)."""
    d = pd.DatetimeIndex(series.index.get_level_values(1))
    start = pd.Timestamp(T) - pd.Timedelta(days=RADAR_HISTORY_DAYS - 1)
    return series[(d >= start) & (d <= pd.Timestamp(T))]


def _link_slowdowns(
    cells: pd.DataFrame, observed: pd.DataFrame, events: pd.DataFrame, T
) -> pd.DataFrame:
    """One row per slowdown event: X, L and age_days (T - date). X NaN: window outside the radar history, so no
    L; it counts only toward n_slowdowns. X = 0: follow-up unobserved, L NaN (never 0). Rows with an L are the
    future fuse/links.parquet (#98, site_id = cell_id under A2). ship_key is never carried. A slowdown whose
    own cell-day has no slowdown U in `cells` gets L NaN even when X > 0."""
    slow = events[events["event_type"] == "slowdown"]
    fine = observed.loc[observed["level"] == FINE, "cell_id"]
    nbrs = neighbours(sorted(set(fine) | set(slow["cell_id"])), PARAMS["link_radius_m"])
    U, E = _radar(_u_small(cells, observed), T), _radar(_exposure(observed), T)
    table = link_table(U, E, nbrs)
    out = slow[["event_id", "cell_id"]].assign(date=_days(slow["time_utc"]).to_numpy())
    u_slow = cells[cells["event_type"] == "slowdown"].assign(date=lambda f: _days(f["date"]))
    out = out.merge(u_slow[["cell_id", "date", "U"]], on=["cell_id", "date"], how="left")
    best, X = _lookup(table, out["cell_id"], out["date"])
    L = np.where((X > 0) & np.isfinite(best), out["U"].to_numpy() * best, np.nan)
    age = (pd.Timestamp(T) - pd.DatetimeIndex(out["date"])).days.to_numpy(float)
    return out.assign(X=X, L=L, age_days=age)


def permutation(
    slowdowns, link_table, n=None, shift_days=PARAMS["shift_days"], seed=None
) -> np.ndarray:
    return np.ones(len(slowdowns))  # stub, issue 24: n = max(999, ceil(10 m / q)) (A3)


def recurrence(L_site, median_L) -> int:  # stub, issue 24
    return 0


def pier_scores(
    sites, travel_hours, tau_h=PARAMS["pier_tau_h"]
) -> tuple[pd.Series, dict[str, list[str]]]:
    return pd.Series(dtype=float), {}  # stub, issue 24


def reasons(site, inputs) -> list[str]:  # stub, issue 24: template, identity-free
    return ["not scored yet (placeholder)"]


def run(observed=None, expected=None, layers=None, travel=None, events=None):
    """Pure (cells, sites) from the input frames; validate.null_test calls it this way.
    With no arguments (make all, DECISIONS.md 2026-11-27 18:30) it reads the stage files and writes fuse/sites."""
    if observed is None:
        return run_sites()
    return _run(observed, expected, layers, travel, events)


def _run(observed, expected, layers, travel, events) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The pure path of run(): frames in, (cells, sites) out, no file I/O (the null test calls it 200 times)."""
    cells = pd.DataFrame(
        {c: pd.Series(dtype=t) for c, t in _CELL_COLUMNS.items()}
    )  # stub, issue 24
    slow = events[events["event_type"] == "slowdown"] if events is not None else pd.DataFrame()
    return cells, suppress(sites(slow))


def run_sites() -> None:
    """Stage files -> fuse/sites.parquet."""
    names = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    _, out = _run(*(io.read_stage(n) for n in names))
    io.write_stage("fuse/sites", out, _provenance("aggregate/observed"))  # type: ignore[arg-type]
