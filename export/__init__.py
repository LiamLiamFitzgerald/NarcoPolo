"""Snapshot export (P7). TEMPORARY PLACEHOLDERS (issue 25): schema-valid simulated content so the
dashboard can render. Replace each TODO(P7) with the real step from docs/specs/P7.md in issue 50."""

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import load

_OUT = Path("export/snapshot.json")
# Stand-alone 9-digit numbers, IMO numbers, call-sign fields (A12: all times are ISO strings).
_IDENTITY = re.compile(
    r"(?<![\d.])\d{9}(?![\d.])|\bIMO[\s:#-]*\d{7}\b|call[\s_-]?sign", re.IGNORECASE
)
_WEEKS = ["2026-W44", "2026-W45", "2026-W46", "2026-W47"]  # TODO(P7): from T via core.time
_CELL = 0.03  # degrees, placeholder cell size


def heatmap_values(expected: Any, cells: Any, exposure: Any, week: str) -> list[dict]:
    """Per cell: the four heat-map values and `observed`. TODO(P7): compute from the stage files.
    Placeholder: a 3 x 3 grid; the last cell is unobserved, so its values are None, never 0."""
    out = []
    for k in range(9):
        r, c = divmod(k, 3)
        seen = k != 8
        out.append(
            {
                "cell_id": f"c{r}{c}",
                "bbox": [
                    -9.5 + c * _CELL,
                    51.5 + r * _CELL,
                    -9.5 + (c + 1) * _CELL,
                    51.5 + (r + 1) * _CELL,
                ],
                "observed": seen,
                "normal": k / 8 if seen else None,
                "obs_vs_exp": (k - 4) / 4 if seen else None,
                "unusual": k / 10 if seen else None,
                "exposure": float(k % 4) if seen else 0.0,
            }
        )
    return out


def basemap(coastline: Any) -> dict:
    """GeoJSON, WGS 84. TODO(P7): simplify(50) in metres, then convert. Placeholder: one land block."""
    ring = [[-9.6, 51.62], [-9.4, 51.62], [-9.4, 51.7], [-9.6, 51.7], [-9.6, 51.62]]
    geom = {"type": "Polygon", "coordinates": [ring]}
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": geom}],
    }


def data_label(provenance: Iterable[str]) -> str:
    """'simulated', 'real' or 'mixed' from the stage files' provenance; never hard-coded."""
    kinds = set(provenance)
    if not kinds or not kinds <= {"simulated", "real"}:
        raise ValueError(f"provenance must be non-empty 'simulated'/'real' values, got {kinds}")
    return kinds.pop() if len(kinds) == 1 else "mixed"


def scan_identities(snapshot: dict) -> None:
    """Raise on anything resembling a vessel identifier."""
    hit = _IDENTITY.search(json.dumps(snapshot))
    if hit:
        raise ValueError(f"possible vessel identifier in snapshot: {hit.group(0)!r}")


def build_snapshot(
    provenance: Iterable[str] = ("simulated",),
    *,
    plan_path: Path = Path("patrol/plan.json"),
    out: Path = _OUT,
) -> dict:
    """Write export/snapshot.json. TODO(P7): read fuse/, forecast/, coverage/, reference/, reports/."""
    cfg, cfg_hash = load()
    bbox = dict(cfg["region_bbox"])
    pos = {
        "S01": (-9.46, 51.56),
        "S02": (-9.40, 51.60),
        "S03": (-9.52, 51.64),
        "base": (-8.32, 51.85),
    }
    plan = {
        a: [{**s, "lon": pos[s["id"]][0], "lat": pos[s["id"]][1]} for s in stops]
        for a, stops in json.loads(plan_path.read_text()).items()
    }
    sites = [
        {
            "id": i,
            "lon": pos[i][0],
            "lat": pos[i][1],
            "S": s,
            "p_perm": p,
            "bh_flag": f,
            "recurrence": 2,
            "agreement": a,
            "followup_unobserved": 0,
            "reasons": ["placeholder reason: unusual slowdown, worth checking"],
            "top_piers": ["P1", "P2"],
        }
        for i, s, p, f, a in [
            ("S01", 0.9, 0.01, True, 3),
            ("S02", 0.6, 0.04, True, 2),
            ("S03", 0.3, 0.3, False, 1),
        ]
    ]
    snap = {
        "meta": {
            "data_label": data_label(provenance),
            "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "region": bbox,
            "week": _WEEKS[-1],
            "weeks": _WEEKS,
            "config_hash": cfg_hash,
            "placeholder": True,
        },
        "basemap": basemap(None),
        "cells": {w: heatmap_values(None, None, None, w) for w in _WEEKS},
        "sites": sites,
        "piers": [
            {"id": "P1", "name": "Placeholder pier A", "lon": -9.44, "lat": 51.58, "P_j": 0.8},
            {"id": "P2", "name": "Placeholder pier B", "lon": -9.38, "lat": 51.57, "P_j": 0.4},
        ],
        "plan": plan,
        # None = not computed yet; nothing here is a real result.
        "validation": {
            "recall": [],
            "forecast_skill": None,
            "calibration_bins": [],
            "brier": None,
            "null_test_flag_share": None,
            "notes": ["placeholder: no validation run"],
        },
    }
    scan_identities(snap)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2))
    return snap


def run() -> None:
    """Entry point for `make all`. TODO(P7): real export in issue 50."""
    build_snapshot()
