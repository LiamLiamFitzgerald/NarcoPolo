"""Patrol plans (P7): a ship route and an aircraft route over the top drop sites, within a time budget.
Orienteering by greedy insertion and 2-opt (docs/specs/P7.md). Ships always use sea distances."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.ndimage import distance_transform_edt
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from core import io
from core.config import load
from core.crs import to_utm
from core.grid import FINE, cell_index
from core.time import iso_week
from patrol import bandit

KN_MS = 0.514444  # 1 kn in m/s (docs/shared.md, Units)
# docs/specs/P7.md Parameters, overlaid by config.yaml's `patrol:` block (#89); aircraft_kn: TODO(P7) confirm
_SPEC = {"top_sites": 15, "ship_kn": 12, "ship_budget_h": 24, "ship_dwell_h": 1,
         "aircraft_kn": 180, "aircraft_budget_h": 4, "aircraft_dwell_h": 0.2}  # fmt: skip
_P = {**_SPEC, **dict(load(io.CONFIG_PATH)[0].get("patrol", {}))}
TOP_SITES = int(_P["top_sites"])
SHIP_KN, AIR_KN = float(_P["ship_kn"]), float(_P["aircraft_kn"])
SHIP_BUDGET_H, SHIP_DWELL_H = float(_P["ship_budget_h"]), float(_P["ship_dwell_h"])
AIR_BUDGET_H, AIR_DWELL_H = float(_P["aircraft_budget_h"]), float(_P["aircraft_dwell_h"])
SEA_RES_M = 250  # the spec's sea_250m.tif resolution


@dataclass(frozen=True)
class _Sea:
    """True = sea. Row 0 is the southern edge; pixel (row, col) covers [x0 + col*res, ...) in metres."""

    mask: np.ndarray
    x0: float
    y0: float
    res: float


def _data_root() -> Path:
    return io.stage_path("aggregate/observed").parent.parent  # NARCO_DATA, default data/


def _sea_from_cells(cells: pd.DataFrame) -> _Sea:
    """Sea grid at 250 m from the 2 km cells of reference/layers.gpkg.
    shortcut: the spec reads reference/sea_250m.tif (MCP_Geometric); no raster or reader exists yet
    (issue 89). Switch to the raster when it does."""
    fine = cells[cells["level"] == FINE]
    c = fine.geometry.centroid
    ix, iy = cell_index(c.x, c.y, FINE)
    ix0, iy0 = ix.min(), iy.min()
    coarse = np.zeros((iy.max() - iy0 + 1, ix.max() - ix0 + 1), bool)
    coarse[iy - iy0, ix - ix0] = True
    k = FINE // SEA_RES_M
    cfg, _ = load(io.CONFIG_PATH)
    return _Sea(
        np.kron(coarse, np.ones((k, k), bool)),
        cfg["x0"] + ix0 * FINE,
        cfg["y0"] + iy0 * FINE,
        float(SEA_RES_M),
    )


def sea_hours(nodes: list[dict], sea: _Sea, kn: float = SHIP_KN) -> np.ndarray:
    """Hours between nodes (dicts with x_m, y_m) by sea only: the shortest path over sea pixels, 8
    neighbours, a diagonal step costs sqrt(2) (the MCP_Geometric cost model). Land is impassable, so
    a headland is gone round, never crossed; unreachable pairs are inf. A node on land (a pier) moves
    to the nearest sea pixel."""
    mask = sea.mask
    ny, nx = mask.shape
    ids = np.full(mask.shape, -1)
    ids[mask] = np.arange(mask.sum())
    src, dst, cost = [], [], []
    for dy, dx, w in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, 2**0.5), (1, -1, 2**0.5)):
        a = ids[: ny - dy, max(0, -dx) : nx - max(0, dx)]
        b = ids[dy:, max(0, dx) : nx - max(0, -dx)]
        both = (a >= 0) & (b >= 0)
        src.append(a[both])
        dst.append(b[both])
        cost.append(np.full(both.sum(), w * sea.res))
    n = int(mask.sum())
    graph = csr_matrix(
        (np.concatenate(cost), (np.concatenate(src), np.concatenate(dst))), shape=(n, n)
    )

    _, (near_r, near_c) = distance_transform_edt(~mask, return_indices=True)  # pyright: ignore[reportGeneralTypeIssues]
    col = np.clip(
        ((np.array([p["x_m"] for p in nodes]) - sea.x0) // sea.res).astype(int), 0, nx - 1
    )
    row = np.clip(
        ((np.array([p["y_m"] for p in nodes]) - sea.y0) // sea.res).astype(int), 0, ny - 1
    )
    at = ids[near_r[row, col], near_c[row, col]]
    metres = dijkstra(graph, directed=False, indices=at)[:, at]
    return metres / (kn * KN_MS * 3600)


def air_hours(nodes: list[dict], kn: float = AIR_KN) -> np.ndarray:
    """Straight-line hours between nodes (x_m, y_m in metres)."""
    xy = np.array([[n["x_m"], n["y_m"]] for n in nodes], dtype=float)
    d = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    return d / (kn * KN_MS * 3600)


def _total(route: list[int], hours: np.ndarray, dwell_h: float) -> float:
    return sum(hours[a, b] for a, b in pairwise(route)) + dwell_h * (len(route) - 2)


def _greedy(
    route: list[int], S: np.ndarray, hours: np.ndarray, budget_h: float, dwell_h: float
) -> list[int]:
    """Add, one at a time, the node with the highest S / extra hours at its cheapest position,
    while the whole trip (legs and dwells) stays within the budget."""
    route = list(route)
    left = set(range(1, len(S))) - set(route)
    while True:
        total, best = _total(route, hours, dwell_h), None
        for i in sorted(left):
            legs = [hours[a, i] + hours[i, b] - hours[a, b] for a, b in pairwise(route)]
            pos = int(np.argmin(legs))
            extra = legs[pos] + dwell_h
            if not np.isfinite(extra) or total + extra > budget_h:
                continue  # over budget, or unreachable
            if best is None or S[i] / extra > best[0]:
                best = (S[i] / extra, i, pos + 1)
        if best is None:
            return route
        route.insert(best[2], best[1])
        left.remove(best[1])


def greedy_route(
    nodes: list[Any], S: np.ndarray, hours: np.ndarray, budget_h: float, dwell_h: float
) -> list[int]:
    """Node indices, node 0 (the base) first and last. S[0] is unused."""
    return _greedy([0, 0], S, hours, budget_h, dwell_h)


def _exact(S: np.ndarray, hours: np.ndarray, budget_h: float, dwell_h: float) -> list[int]:
    """Exact orienteering by DP over subsets (Held-Karp): the in-budget set of sites with the highest
    total S, in its shortest order. Ties go to the shorter trip. Node 0 is the base; S[0] is unused.
    Cost is 2^m * m^2 for m sites, so the caller keeps m below learn.exact_max_nodes."""
    m = len(S) - 1
    if m == 0:
        return [0, 0]
    bits = 1 << np.arange(m)
    leg = hours[1:, 1:] + dwell_h  # site j -> site k, plus the dwell at k
    dp = np.full((1 << m, m), np.inf)  # dp[mask, k]: hours from the base through mask, ending at k
    par = np.full((1 << m, m), -1)
    dp[bits, np.arange(m)] = hours[0, 1:] + dwell_h
    pop = np.bitwise_count(np.arange(1 << m))
    for c in range(2, m + 1):
        masks = np.flatnonzero(pop == c)
        prev = masks[:, None] ^ bits[None, :]  # (masks, k): the mask before k was added
        val = dp[prev] + leg.T[None, :, :]  # [mask, k, j] = dp[prev, j] + leg[j, k]
        val[(masks[:, None] & bits[None, :]) == 0] = np.inf  # k must be in mask
        j = val.argmin(axis=2)
        best = np.take_along_axis(val, j[..., None], axis=2)[..., 0]
        best[best > budget_h] = (
            np.inf
        )  # legs never shrink, so an over-budget partial trip stays over
        dp[masks], par[masks] = best, j
    back = dp + hours[1:, 0][None, :]
    total = back.min(axis=1)
    ok = total <= budget_h
    if not ok.any():
        return [0, 0]
    value = ((np.arange(1 << m)[:, None] & bits[None, :]) > 0).astype(float) @ S[1:]
    cand = np.flatnonzero(ok)
    mask = int(cand[np.lexsort((total[cand], -value[cand]))[0]])
    k, route = int(back[mask].argmin()), []
    while mask:
        route.append(k + 1)
        mask, k = mask ^ (1 << k), int(par[mask, k])
    return [0, *route[::-1], 0]


def two_opt(route: list[int], hours: np.ndarray) -> list[int]:
    """Reverse any segment that shortens the route, until none does. The ends (the base) stay put."""
    route = list(route)
    better = True
    while better:
        better = False
        for i in range(1, len(route) - 2):
            for j in range(i + 1, len(route) - 1):
                a, b, c, d = route[i - 1], route[i], route[j], route[j + 1]
                if hours[a, c] + hours[b, d] < hours[a, b] + hours[c, d] - 1e-9:
                    route[i : j + 1] = route[i : j + 1][::-1]
                    better = True
    return route


def _greedy_inputs(sites: pd.DataFrame) -> pd.DataFrame:
    """The top 15 candidates: by p_site once the site model writes it (learning L5), else flagged sites
    by S, filled with unflagged ones by S when fewer."""
    if "p_site" in sites:
        return sites.sort_values("p_site", ascending=False, kind="stable").head(TOP_SITES)
    ranked = sites.sort_values(["bh_flag", "S"], ascending=[False, False], kind="stable")
    return ranked.head(TOP_SITES)


def _plan_asset(
    sites: pd.DataFrame,
    base: tuple[float, float],
    hours_fn,
    *,
    budget_h: float,
    dwell_h: float,
    start: pd.Timestamp,
    stand_in: bool = False,
    theta: pd.Series | None = None,
    exploit: pd.Series | None = None,
    exact_max_nodes: int = 0,
) -> list[dict]:
    """theta (by site_id) replaces S as node weights (bandit, learning L5): the Thompson draw is the one
    exploration method (D3, #176). A stop is 'exploit' if it is also on the route planned with the `exploit`
    weights (posterior means), else 'explore', which is marked `exploration` for the snapshot and dashboard.
    Without theta (no bandit state), the route is the greedy fill on S."""
    cand = _greedy_inputs(sites).reset_index(drop=True)
    nodes = [
        {"x_m": base[0], "y_m": base[1]},
        *({"x_m": r.x_m, "y_m": r.y_m} for r in cand.itertuples()),
    ]
    hours = hours_fn(nodes)

    if theta is not None:
        exact = len(nodes) <= exact_max_nodes

        def solve(w: pd.Series) -> list[int]:
            S = np.array([0.0, *w.loc[cand["site_id"]]])
            if exact:
                return _exact(S, hours, budget_h, dwell_h)
            return two_opt(_greedy([0, 0], S, hours, budget_h, dwell_h), hours)

        route = solve(theta)
        on_mean = set(solve(exploit if exploit is not None else theta))
    else:
        S = np.array([0.0, *cand["S"]])
        route, on_mean = two_opt(_greedy([0, 0], S, hours, budget_h, dwell_h), hours), set()

    stops, t = [], start
    for k, i in enumerate(route):
        if k:
            t += pd.Timedelta(hours=float(hours[route[k - 1], i]) + (dwell_h if k > 1 else 0))
        stop = {
            "id": "base" if i == 0 else cand["site_id"][i - 1],
            "arrival_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dwell_h": 0 if i == 0 else dwell_h,
            "x_m": nodes[i]["x_m"],
            "y_m": nodes[i]["y_m"],
        }
        if i == 0 and stand_in:
            stop["stand_in"] = (
                True  # base position or start time is a simulated stand-in (issue 103)
            )
        if i and not cand["bh_flag"][i - 1]:
            stop["not_significant"] = True
        if i and theta is not None:
            stop["theta"] = float(theta[stop["id"]])
            stop["reason"] = "exploit" if i in on_mean else "explore"
            if stop["reason"] == "explore":
                stop["exploration"] = True
        stops.append(stop)
    return stops


def _provenance(name: str) -> Literal["simulated", "real"]:
    """shortcut: reads core.io's stamp layout directly; ask P1 for a public read_stamp (issue 89)."""
    path = io.stage_path(name)
    if name.startswith("reference/"):
        raw = path.with_name(f"layers.{name.split('/')[1]}.stamp.json").read_bytes()
    else:
        raw = (pq.read_schema(path).metadata or {})[b"narco"]
    return json.loads(raw)["provenance"]


def _base(cfg: Mapping[str, Any]) -> tuple[tuple[float, float], bool]:
    """((x_m, y_m), stand_in). The base is `base_port` {lon, lat} in config.yaml (the spec: Haulbowline,
    Cork Harbour). It is not there yet (issue 103), and P7 does not guess a position: simulated data uses
    the first road-access pier as a stand-in, real data refuses to run."""
    bp = cfg.get("base_port")
    if bp:
        x, y = to_utm(bp["lon"], bp["lat"])
        return (float(x), float(y)), False
    if _provenance("reference/piers") == "real":
        raise ValueError("base_port {lon, lat} is not in config.yaml: see issue 103")
    piers = io.read_stage("reference/piers")
    p = piers[piers["road_access"]].sort_values("pier_id").geometry.iloc[0]
    return (float(p.x), float(p.y)), True


def _start(cfg: Mapping[str, Any]) -> tuple[pd.Timestamp, bool]:
    """(start, stand_in). The plan starts `patrol_start_hour_utc` hours into the day after T; the spec
    gives no start time (issue 103), so simulated data starts at 00:00 as a stand-in and real data refuses."""
    hour = cfg.get("patrol_start_hour_utc")
    stand_in = hour is None
    if stand_in:
        if _provenance("fuse/sites") == "real":
            raise ValueError("patrol_start_hour_utc is not in config.yaml: see issue 103")
        hour = 0
    start = pd.Timestamp(io.read_snapshot()["T"], tz="UTC") + pd.Timedelta(days=1, hours=hour)
    return start, stand_in


def _write(asset: str, stops: list[dict]) -> dict:
    try:
        plan = io.read_json_stage("patrol/plan")
    except ValueError:  # no plan yet, or one made with an older config: start again
        plan = {}
    plan[asset] = stops
    io.write_json_stage("patrol/plan", plan, _provenance("fuse/sites"))
    return plan


def _bandit(cfg: Mapping[str, Any], sites: pd.DataFrame, seed: int) -> dict[str, Any]:
    """Learning L5: the saved posterior, with new top sites warm-started from their prior (sites that
    leave the top keep their state), one seeded Thompson draw, and the state written back."""
    try:
        state = io.read_json_stage("patrol/bandit_state")
    except ValueError:  # no state yet, or one made with an older config: start from the priors
        state = {}
    learn = cfg["learn"]
    state = {**bandit.prior(_greedy_inputs(sites), learn["prior_strength"]), **state}
    io.write_json_stage("patrol/bandit_state", state, _provenance("fuse/sites"))
    return {
        "theta": bandit.sample(state, seed),
        "exploit": bandit._mean(state),
        "exact_max_nodes": int(learn["exact_max_nodes"]),
    }


def ship_plan() -> dict:
    """Ship route over the top sites, weighted by the bandit's Thompson draw; merged into patrol/plan.json."""
    cfg, _ = load(io.CONFIG_PATH)
    sea = _sea_from_cells(io.read_stage("reference/cells"))
    (base, base_stand_in), (start, start_stand_in) = _base(cfg), _start(cfg)
    seed = int(cfg["seed"]) + iso_week(io.read_snapshot()["T"])[1]
    sites = io.read_stage("fuse/sites")
    stops = _plan_asset(
        sites, base, lambda n: sea_hours(n, sea, SHIP_KN),
        budget_h=SHIP_BUDGET_H, dwell_h=SHIP_DWELL_H, start=start,
        stand_in=base_stand_in or start_stand_in, **_bandit(cfg, sites, seed),
    )  # fmt: skip
    return _write("ship", stops)


def aircraft_plan() -> dict:
    """The same planner and the same draw (same seed) with straight-line distances."""
    cfg, _ = load(io.CONFIG_PATH)
    (base, base_stand_in), (start, start_stand_in) = _base(cfg), _start(cfg)
    seed = int(cfg["seed"]) + iso_week(io.read_snapshot()["T"])[1]
    sites = io.read_stage("fuse/sites")
    stops = _plan_asset(
        sites, base, lambda n: air_hours(n, AIR_KN),
        budget_h=AIR_BUDGET_H, dwell_h=AIR_DWELL_H, start=start,
        stand_in=base_stand_in or start_stand_in, **_bandit(cfg, sites, seed),
    )  # fmt: skip
    return _write("aircraft", stops)


def run() -> None:
    """Entry point for `make all`."""
    ship_plan()
    aircraft_plan()
