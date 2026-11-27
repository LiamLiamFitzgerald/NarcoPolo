"""Patrol plans (P7). TEMPORARY PLACEHOLDERS (issue 25): schema-valid output so the pipeline runs
end to end. Replace each TODO(P7) with the real step from docs/specs/P7.md in issue 49."""

import json
from pathlib import Path

import numpy as np

KN_MS = 0.514444  # 1 kn in m/s (docs/shared.md, Units)
# TODO(P7): these belong in config.yaml (P1 owns it): ship_kn, aircraft_kn, budgets, dwells, n_boot.
SHIP_KN, AIR_KN = 12, 180
SHIP_BUDGET_H, SHIP_DWELL_H = 24, 1
AIR_BUDGET_H, AIR_DWELL_H = 4, 0.2
# TODO(P7): replace with the real stop times derived from the snapshot date T.
_T0 = "2026-11-23T06:00:00Z"
_PLAN = Path("patrol/plan.json")


def sea_hours(nodes: list[dict], sea: np.ndarray, kn: float = SHIP_KN) -> np.ndarray:
    """Hours between nodes by sea. TODO(P7): MCP_Geometric on sea_250m.tif; constant 1 h for now."""
    n = len(nodes)
    return np.ones((n, n)) - np.eye(n)


def air_hours(nodes: list[dict], kn: float = AIR_KN) -> np.ndarray:
    """Straight-line hours between nodes (x_m, y_m in metres)."""
    xy = np.array([[n["x_m"], n["y_m"]] for n in nodes], dtype=float)
    d = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    return d / (kn * KN_MS * 3600)


def greedy_route(
    nodes: list[dict], S: np.ndarray, hours: np.ndarray, budget_h: float, dwell_h: float
) -> list[int]:
    """Node indices, base (0) first and last. TODO(P7): insertion by S / extra hours; this adds
    nodes by S, at the end of the route, while the trip back still fits the budget."""
    route, total = [0], 0.0
    for i in sorted(range(1, len(nodes)), key=lambda i: -S[i]):
        extra = hours[route[-1], i] + dwell_h + hours[i, 0] - hours[route[-1], 0]
        if total + extra + hours[route[-1], 0] <= budget_h:
            total += hours[route[-1], i] + dwell_h
            route.append(i)
    return [*route, 0]


def two_opt(route: list[int], hours: np.ndarray) -> list[int]:
    """TODO(P7): reverse segments that shorten the route. Returns the route unchanged for now."""
    return route


def exploration_pick(sites_4_to_15: list[str], n_boot: int = 200, seed: int = 0) -> str:
    """One site id. TODO(P7): bootstrap each site's L, draw once each, take the highest.
    Seeded (seed = global seed + ISO week) so the demo plan never changes between runs."""
    return sites_4_to_15[np.random.default_rng(seed).integers(len(sites_4_to_15))]


def _stops(ids: list[str], hours: float, dwell_h: float) -> list[dict]:
    """Placeholder stops: equal legs of `hours`, arrival as an ISO string (A12)."""
    t0 = np.datetime64(_T0.rstrip("Z"))
    out = []
    for k, i in enumerate(ids):
        at = t0 + np.timedelta64(round(k * (hours + dwell_h) * 3600), "s")
        out.append({"id": i, "arrival_utc": f"{at}Z", "dwell_h": 0 if i == "base" else dwell_h})
    return out


def _write(asset: str, stops: list[dict], out: Path) -> dict:
    plan = json.loads(out.read_text()) if out.exists() else {}
    plan[asset] = stops
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2))
    return plan


def ship_plan(*, out: Path = _PLAN) -> dict:
    """TODO(P7): top sites from fuse/sites.parquet, sea_hours, greedy_route, two_opt, exploration."""
    return _write("ship", _stops(["base", "S01", "S02", "base"], 1.5, SHIP_DWELL_H), out)


def aircraft_plan(*, out: Path = _PLAN) -> dict:
    """TODO(P7): the same planner with air_hours and no exploration slot."""
    return _write("aircraft", _stops(["base", "S01", "S02", "S03", "base"], 0.2, AIR_DWELL_H), out)
