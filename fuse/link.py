"""Lag link (issue 56), drop sites, significance and recurrence (issue 57), pier scores and reasons (issue 59)."""

import math
from typing import NamedTuple

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from core import io
from core.grid import FINE, centroid, neighbours
from fuse._common import _CFG, PARAMS, RADAR_HISTORY_DAYS, _provenance
from fuse.features import site_features
from fuse.learn import _add_learning_columns

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


def _empty_sites() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in _SITE_COLUMNS.items()})


def sites(slowdowns: pd.DataFrame) -> pd.DataFrame:
    """One site per 2 km cell of its slowdowns (A2, no DBSCAN). slowdowns: _link_slowdowns rows (cell_id, X, L,
    age_days). L NaN adds nothing to S or recurrence but counts in n_slowdowns; X = 0 counts as follow-up
    unobserved. p_perm, bh_flag and agreement are neutral here and filled by the permutation step."""
    if slowdowns.empty:
        return _empty_sites()
    median_L = float(np.nanmedian(slowdowns["L"])) if slowdowns["L"].notna().any() else math.inf
    rows = []
    for cid, g in slowdowns.groupby("cell_id", sort=True):
        x, y = centroid(str(cid))
        rows.append(
            {
                "site_id": str(cid),
                "x_m": x,
                "y_m": y,
                "n_slowdowns": len(g),
                "S": site_score(g["L"], g["age_days"]),
                "p_perm": 1.0,
                "bh_flag": False,
                "recurrence": recurrence(g["L"], median_L),
                "followup_unobserved": int((g["X"] == 0).sum()),
                "agreement": 0,
                "reasons": [],
                "top_piers": [],
            }
        )
    return pd.DataFrame(rows).astype({c: t for c, t in _SITE_COLUMNS.items() if t is not object})


def suppress(ranked_sites: pd.DataFrame, radius_m=PARAMS["link_radius_m"]) -> pd.DataFrame:
    """The top list: walk sites in the given rank order and drop any within radius_m of a site already kept
    (it is "nearby" that one). Distances between site centres in metres."""
    keep: list[int] = []
    xy = ranked_sites[["x_m", "y_m"]].to_numpy(float)
    for i in range(len(ranked_sites)):
        if all(math.hypot(*(xy[i] - xy[j])) > radius_m for j in keep):
            keep.append(i)
    return ranked_sites.iloc[keep]


def site_score(L, ages, half_life=PARAMS["half_life_days"]) -> float:
    """S = sum of L x 2^(-age / half_life) over slowdowns with a link score; missing L (None/NaN) add nothing."""
    L, a = np.asarray(L, float), np.asarray(ages, float)
    ok = np.isfinite(L)
    return float(np.sum(L[ok] * 2.0 ** (-a[ok] / half_life)))


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


def _shuffle_scores(
    d: np.ndarray,
    ci: np.ndarray,
    U: np.ndarray,
    site: np.ndarray,
    n_sites: int,
    table: LinkTable,
    offsets: np.ndarray,
) -> np.ndarray:
    """S per (offset, site) with every slowdown moved by the same offset, wrapping within the days that have
    small-boat scores (#177); each keeps its cell and U. L follows the moved date (A4: lookups); the age
    decay keeps the real date (#177), so a shuffle changes timing, not recency."""
    span = table.X.shape[1]
    # #177: wrap within the days that have small-boat scores (the scored window); outside it no link is possible,
    # so shifting a slowdown there would lower S for reasons that have nothing to do with timing.
    days = np.flatnonzero(np.isfinite(table.best).any(axis=0))
    lo, width = (int(days[0]), int(days[-1]) - int(days[0]) + 1) if len(days) else (0, span)
    nd = lo + (d[None, :] - lo + offsets[:, None]) % width
    best, X = table.best[ci[None, :], nd], table.X[ci[None, :], nd]
    L = np.where((X > 0) & np.isfinite(best), U[None, :] * best, 0.0)
    # #177: the age stays with the slowdown's real date. U exists only in the recent scored window, so decaying at the
    # moved date made every shuffle look older (lower S) and every linked site look significant. The shift tests
    # timing, not recency.
    w = L * 2.0 ** (-(span - 1 - d[None, :]) / PARAMS["half_life_days"])
    out = np.zeros((len(offsets), n_sites))
    for k in range(len(offsets)):
        out[k] = np.bincount(site, weights=w[k], minlength=n_sites)
    return out


def permutation(
    slowdowns, link_table, n=None, shift_days=PARAMS["shift_days"], seed=None
) -> pd.Series:
    """p_perm per site (index site_id = cell_id). Tested: sites with at least one linked slowdown (m of them);
    the rest get 1.0. n = max(n_shuffles, ceil(10 m / q)) shuffles (A3), each one random offset in
    [-shift_days, shift_days] for all slowdowns. p = (1 + shuffles with S >= observed) / (n + 1). Slowdowns
    outside the link table (no L possible) are left out; moved ones landing on unobserved windows get no L,
    exactly like real ones. Observed S is the zero-offset lookup, so it is computed the same way."""
    all_sites = pd.Index(sorted(slowdowns["cell_id"].astype(str).unique()), name="site_id")
    p = pd.Series(1.0, index=all_sites, name="p_perm")
    ci = link_table.cells.get_indexer(pd.Index(slowdowns["cell_id"]))
    d = (_days(slowdowns["date"]) - link_table.day0).days.to_numpy()
    U = slowdowns["U"].to_numpy(float)
    ok = (ci >= 0) & (d >= 0) & (d < link_table.X.shape[1]) & np.isfinite(U)
    if not ok.any():
        return p
    site_ids = all_sites.get_indexer(pd.Index(slowdowns["cell_id"].astype(str)))[ok]
    args = (d[ok], ci[ok], U[ok], site_ids, len(all_sites), link_table)
    observed = _shuffle_scores(*args, offsets=np.zeros(1, int))[0]
    tested = observed > 0
    m = int(tested.sum())
    if m == 0:
        return p
    if n is None:
        n = max(int(PARAMS["n_shuffles"]), math.ceil(10 * m / PARAMS["fdr_q"]))
    if seed is None:
        seed = int(_CFG["seed"]) + int(PARAMS["perm_seed_offset"])
    rng = np.random.default_rng(seed)
    ge = np.zeros(len(all_sites))
    for start in range(0, n, 500):  # chunks keep memory at 500 x slowdowns
        offsets = rng.integers(-shift_days, shift_days + 1, min(500, n - start))
        ge += (_shuffle_scores(*args, offsets=offsets) >= observed[None, :] - 1e-12).sum(axis=0)
    p[tested] = (1 + ge[tested]) / (n + 1)
    return p


def recurrence(L_site, median_L) -> int:
    """Distinct slowdowns of the site whose link score is above the median L of all slowdowns."""
    L = np.asarray(L_site, float)
    return int(np.sum(np.isfinite(L) & (L > median_L)))


def _strongest(slow: pd.DataFrame, u_small: pd.Series, agree: pd.Series, nbrs) -> pd.DataFrame:
    """Per site (index site_id): the dark_small cell-day that gave its highest L, with its agreement (P6 Resolved
    ambiguities), the lag in days after that slowdown and the slowdown's own row (for the reasons)."""
    rows = {}
    for cid, g in slow[slow["L"] > 0].groupby("cell_id"):
        s = g.nlargest(1, "L").iloc[0]  # first row with the highest L, as idxmax
        m, d0 = _window(s, u_small, nbrs, PARAMS["link_days"])
        if not m.any():
            continue
        lag = (pd.DatetimeIndex(u_small.index.get_level_values(1)[m]) - d0).days.to_numpy()
        k = int(np.argmax(u_small[m].to_numpy() * np.exp(-lag / PARAMS["tau_days"])))
        key = u_small.index[m][k]
        rows[str(cid)] = {
            "agreement": int(agree.reindex([key]).fillna(0).iloc[0]),
            "small_cell": key[0], "small_date": pd.Timestamp(key[1]), "lag_days": int(lag[k]),
            "event_id": s["event_id"],
        }  # fmt: skip
    return pd.DataFrame.from_dict(rows, orient="index")


_NO_PIER = "no road-access pier within reach"


def _scored(sites: pd.DataFrame) -> pd.DataFrame:
    """Sites that feed pier scores: the flagged ones, else the top 5 unflagged by S (shown as "not significant")."""
    flagged = sites[sites["bh_flag"]]
    return flagged if len(flagged) else sites.sort_values("S", ascending=False).head(5)


def pier_scores(
    sites, travel_hours, tau_h=PARAMS["pier_tau_h"]
) -> tuple[pd.Series, dict[str, list[str]]]:
    """P_j = sum over scored sites of S x exp(-T / tau_h), T = sea-only travel hours (site_id = cell_id, A2), and
    each scored site's top 3 piers by that weight. travel_hours must already be road-access piers only; a pier
    with no travel row is unreachable by sea and gets nothing. Scored = flagged, else the top 5 unflagged."""
    scored = _scored(sites)[["site_id", "S"]]
    t = travel_hours.merge(scored, left_on="cell_id", right_on="site_id")
    t = t.assign(w=t["S"] * np.exp(-t["hours"] / tau_h))
    P = t.groupby("pier_id")["w"].sum().rename("P_j")
    top = {
        str(sid): g.sort_values(["w", "pier_id"], ascending=[False, True])["pier_id"]
        .head(3)
        .tolist()
        for sid, g in t[t["w"] > 0].groupby("site_id")
    }
    return P, top


def _fmt(x: float) -> str:
    return f"{x:.1f}" if x < 10 else f"{x:.0f}"


def reasons(site, inputs) -> list[str]:
    """Plain-language evidence for one site, filled from its numbers. Identity-free: no vessel or person, only
    the cell, counts and times as day offsets. Language rule: "unusual", "worth checking", never a verdict.
    inputs: mapping with optional keys strongest (row of _strongest), C and mu (small-boat count and expected
    count on that cell-day), dist_coast_m, lane, inshore_frac, n_tested, significant (bool)."""
    out = [f"{int(site['n_slowdowns'])} ship slowdown(s) in this 2 km cell."]
    st = inputs.get("strongest")
    if st is not None:
        line = f"{int(st['lag_days'])} day(s) after the strongest one: unusual small-boat activity nearby"
        if inputs.get("C") is not None and inputs.get("mu") is not None:
            line += f", {_fmt(inputs['C'])} small unmatched detection(s) where {_fmt(inputs['mu'])} were expected"
        out.append(line + ".")
        out.append(
            f"{int(st['agreement'])} of 4 detector angles agree on that follow-up (angles, not votes)."
        )
    else:
        out.append("No small-boat activity seen after these slowdowns.")
    if int(site["recurrence"]) > 1:
        out.append(
            f"Reused: {int(site['recurrence'])} slowdowns with a stronger-than-median follow-up."
        )
    if int(site["followup_unobserved"]) > 0:
        out.append(
            f"{int(site['followup_unobserved'])} slowdown(s) had no calm radar pass within "
            f"{PARAMS['link_days']} days: follow-up unobserved, not 'nothing came'."
        )
    d = inputs.get("dist_coast_m")
    if d is not None and np.isfinite(d):
        out.append(
            f"{d / 1000:.0f} km from the coast"
            + (", in a shipping lane." if inputs.get("lane") else ", outside lanes.")
        )
    f = inputs.get("inshore_frac")
    if f is not None and np.isfinite(f) and f < 0.1:
        out.append("Outside inshore fishing grounds.")
    if inputs.get("significant"):
        out.append(
            f"Worth checking: busy traffic alone rarely scores this high (p = {site['p_perm']:.3g}, "
            f"still unusual after correcting for {inputs.get('n_tested', 0)} sites)."
        )
    elif inputs.get("tested", True):
        out.append(
            f"Not flagged (p = {site['p_perm']:.3g} over {inputs.get('n_tested', 0)} tested sites): busy traffic "
            "alone could explain this score, or there is not enough history yet to tell."
        )
    else:
        out.append("Not tested: outside the top sites by score.")
    return out


def run(observed=None, expected=None, layers=None, travel=None, events=None, cells=None, T=None):
    """Pure (cells, sites) from the input frames; validate.null_test calls it this way and passes `cells` (from
    detectors.scores.score_cells, which fuse may not import) so slowdowns get link scores (#177).
    With no arguments (make all, DECISIONS.md 2026-11-27 18:30) it reads the stage files and writes fuse/sites."""
    if observed is None:
        return run_sites()
    return _run(observed, expected, layers, travel, events, cells=cells, T=T)


def _scored_sites(
    cells: pd.DataFrame, observed: pd.DataFrame, expected: pd.DataFrame, events: pd.DataFrame, T
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(sites, slowdowns, strongest): sites with S, p_perm (permutation through the link table), bh_flag (BH once
    over the tested sites), recurrence, followup_unobserved and agreement, ranked by S and suppressed to the top
    list; the linked slowdowns; and each site's strongest follow-up cell-day."""
    if events is None or not (events["event_type"] == "slowdown").any():
        return _empty_sites(), pd.DataFrame(), pd.DataFrame()
    slow = _link_slowdowns(cells, observed, events, T)
    out = sites(slow)
    fine = observed.loc[observed["level"] == FINE, "cell_id"]
    nbrs = neighbours(sorted(set(fine) | set(slow["cell_id"])), PARAMS["link_radius_m"])
    u_small = _radar(_u_small(cells, observed), T)
    table = link_table(u_small, _radar(_exposure(observed), T), nbrs)
    p = permutation(slow, table)
    out["p_perm"] = p.reindex(out["site_id"]).to_numpy()
    # #177: only the patrol candidates (top-k by S, S > 0) are tested, so BH corrects for k tests, not every cell.
    # A site never needs a flag to be patrolled: p_site and the bandit rank sites; the flag is extra evidence.
    in_top = out["S"].rank(ascending=False, method="first") <= PARAMS["test_top_k"]
    tested = ((out["S"] > 0) & in_top).to_numpy()
    flag = np.zeros(len(out), bool)
    flag[tested] = multipletests(out.loc[tested, "p_perm"], alpha=PARAMS["fdr_q"], method="fdr_bh")[
        0
    ]
    out["bh_flag"] = flag
    agree = _small_rows(cells).set_index(["cell_id", "date"])["agreement"]
    strongest = _strongest(slow, u_small, agree, nbrs)
    a = strongest["agreement"] if len(strongest) else pd.Series(dtype=int)
    out["agreement"] = a.reindex(out["site_id"]).fillna(0).astype(int).to_numpy()
    ranked = suppress(out.sort_values(["S", "site_id"], ascending=[False, True], kind="stable"))
    ranked = ranked.reset_index(drop=True)
    # R3: raw agent scores, as the trainer fits them; no forecast (some pure-path tests) means no features
    feats = None if expected is None else site_features(ranked, observed, expected, T)
    return (
        _add_learning_columns(ranked, PARAMS["fdr_q"], feats),
        slow,
        strongest,
    )


def _road_travel(travel: pd.DataFrame | None, piers: pd.DataFrame | None) -> pd.DataFrame:
    """Travel rows to road-access piers only; without a piers layer (pure path) every pier counts."""
    if travel is None:
        return pd.DataFrame(columns=["cell_id", "pier_id", "hours"])
    if piers is None:
        return travel
    return travel[travel["pier_id"].isin(piers.loc[piers["road_access"].astype(bool), "pier_id"])]


def _finish(sites_, slow, strongest, observed, expected, layers, travel, piers):
    """Fill reasons and top_piers; build fuse/piers (one row per road-access pier) and fuse/links."""
    road = _road_travel(travel, piers)
    P, top = pier_scores(sites_, road)
    scored = set(_scored(sites_)["site_id"]) if len(sites_) else set()
    small = _small_rows(observed).set_index(["cell_id", "date"])["count"] if len(observed) else None
    mu = None
    if expected is not None and len(expected):
        e = (
            expected[expected["fold"] == 0] if "fold" in expected else expected
        )  # live forecast (#198)
        mu = _small_rows(e).set_index(["cell_id", "date"])["mu"]
    lay = layers.set_index("cell_id") if layers is not None and len(layers) else None
    in_top = (
        sites_["S"].rank(ascending=False, method="first") <= PARAMS["test_top_k"]
        if len(sites_)
        else []
    )
    tested_ids = set(sites_.loc[(sites_["S"] > 0) & in_top, "site_id"]) if len(sites_) else set()
    n_tested = len(tested_ids)
    rs, tp = [], []
    for _, site in sites_.iterrows():
        sid = site["site_id"]
        inputs: dict = {
            "n_tested": n_tested,
            "significant": bool(site["bh_flag"]),
            "tested": sid in tested_ids,
        }
        if sid in strongest.index:
            st = strongest.loc[sid]
            inputs["strongest"] = st
            key = (st["small_cell"], st["small_date"])
            for name, series in (("C", small), ("mu", mu)):
                if series is not None and key in series.index:
                    inputs[name] = float(np.asarray(series.loc[key]).ravel()[0])
        if lay is not None and sid in lay.index:
            for c in ("dist_coast_m", "lane", "inshore_frac"):
                if c in lay.columns:
                    inputs[c] = lay.at[sid, c]
        r = reasons(site, inputs)
        piers_ = top.get(sid, [])
        if sid in scored and not piers_:
            r.append(_NO_PIER.capitalize() + ".")
        rs.append(r)
        tp.append(piers_)
    sites_ = sites_.assign(reasons=rs, top_piers=tp)
    all_piers = pd.Index(sorted(set(road["pier_id"])), name="pier_id")
    piers_out = P.reindex(all_piers).fillna(0.0).reset_index()
    links = pd.DataFrame(columns=["site_id", "L", "age_days"])
    if len(slow):
        lk = slow[slow["L"].notna() & slow["cell_id"].isin(sites_["site_id"])]
        links = pd.DataFrame(
            {
                "site_id": lk["cell_id"].astype(str),
                "L": lk["L"].astype(float),
                "age_days": lk["age_days"].astype(float),
            }
        ).reset_index(drop=True)
    return sites_, piers_out, links


def _run(
    observed, expected, layers, travel, events, cells=None, T=None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The pure path of run(): frames in, (cells, sites) out, no file I/O (the null test calls it 200 times).
    fuse may not import detectors/ (tach), so cell scores come in as `cells`; without them every U is unknown,
    no slowdown gets a link score and no site is flagged. T defaults to the last observed date."""
    if cells is None:
        cells = pd.DataFrame({c: pd.Series(dtype=t) for c, t in _CELL_COLUMNS.items()})
    return cells, _all(observed, expected, layers, travel, events, cells, T)[0]


def _all(observed, expected, layers, travel, events, cells, T, piers=None):
    """(sites, piers, links) from frames; no file I/O."""
    if T is None:
        T = pd.Timestamp(max(observed["date"])).date() if len(observed) else None
    s, slow, strongest = _scored_sites(cells, observed, expected, events, T)
    return _finish(s, slow, strongest, observed, expected, layers, travel, piers)


def run_sites() -> None:
    """Stage files -> fuse/sites, fuse/piers and fuse/links."""
    names = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    cells = io.read_stage("fuse/cells")  # written by detectors.run_cells, which make all runs first
    frames = [io.read_stage(n) for n in names]
    sites_, piers, links = _all(
        *frames, cells=cells, T=io.read_snapshot()["T"], piers=io.read_stage("reference/piers")
    )
    prov = _provenance("aggregate/observed")
    io.write_stage("fuse/sites", sites_, prov)  # type: ignore[arg-type]
    io.write_stage("fuse/piers", piers, prov)  # type: ignore[arg-type]
    io.write_stage("fuse/links", links, prov)  # type: ignore[arg-type]
