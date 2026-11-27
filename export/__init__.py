"""Snapshot export (P7): freeze the plan, heat maps, sites, piers and validation into one JSON file.
The dashboard only draws what is written here (docs/specs/P7.md)."""

import json
import os
import re
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import transform, unary_union
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.crs import to_wgs84
from core.time import iso_week

# What export reads (the spec's inputs that have a schema). reports/validation.json and
# patrol/plan.json are plain JSON.
_INPUTS = (
    "fuse/sites",
    "fuse/cells",
    "forecast/expected",
    "coverage/exposure",
    "reference/cells",
    "reference/piers",
)
# Stand-alone 9-digit numbers (not part of a word, so the end of a hex hash such as the config hash
# is not an MMSI), IMO numbers, call-sign / MMSI fields, the internal ship_key (A12: all times are
# ISO strings, so they never look like a bare 9-digit number).
_IDENTITY = re.compile(
    r"(?<![\w.])\d{9}(?![\w.])|\bIMO[\s:#-]*\d{7}\b|call[\s_-]?sign|\bmmsi\b|ship_key",
    re.IGNORECASE,
)


def _data_root() -> Path:
    return io.stage_path("aggregate/observed").parent.parent  # NARCO_DATA, default data/


def _num(v: Any) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), 4)


def _provenance(name: str) -> str:
    """'simulated' or 'real', from the stamp core.io wrote into the stage file.
    shortcut: reads core.io's stamp layout directly; ask P1 for a public read_stamp."""
    path = io.stage_path(name)
    if name.startswith("reference/"):  # a GeoPackage layer: the stamp is a sidecar file
        raw = path.with_name(f"layers.{name.split('/')[1]}.stamp.json").read_bytes()
    else:
        raw = (pq.read_schema(path).metadata or {})[b"narco"]
    return json.loads(raw)["provenance"]


def _weeks(t: date) -> list[str]:
    """The ISO week containing T and the 3 before (Global settings)."""
    monday = t - timedelta(days=t.weekday())
    return ["{}-W{:02d}".format(*iso_week(monday - timedelta(weeks=k))) for k in (3, 2, 1, 0)]


def heatmap_values(
    expected: pd.DataFrame, cells: pd.DataFrame, exposure: pd.DataFrame, week: str
) -> list[dict]:
    """Per cell for one ISO week: the four heat-map values and `observed` (small-boat exposure > 0).

    normal    mean over observed days of mu / E for dark_small     (forecast/expected, coverage)
    obs_vs_exp  always None: needs y in fuse/cells (contract issue 87)
    unusual   weekly max of U over both event types                (fuse/cells)
    agreement the 0-4 badge of the row that gave that maximum      (fuse/cells)
    exposure  summed small-boat exposure in the week               (coverage/exposure)
    A value that cannot be computed is None, never 0 (Design principle 4)."""
    year, w = week.split("-W")
    first = date.fromisocalendar(int(year), int(w), 1)
    in_week = lambda d: (d >= first) & (d <= first + timedelta(days=6))

    ex = exposure.assign(day=exposure["time_utc"].dt.date)  # UTC dates
    daily = ex[in_week(ex["day"])].groupby(["cell_id", "day"])["exposure_small"].sum()
    weekly = (
        daily.groupby("cell_id").sum().reindex(sorted(exposure["cell_id"].unique()), fill_value=0.0)
    )

    small = expected[expected["event_type"] == "dark_small"]
    small = small.assign(day=pd.to_datetime(small["date"]).dt.date)
    mu = small.set_index(["cell_id", "day"])[
        "mu"
    ]  # same level names as `daily`, or pandas misaligns
    normal = (mu / daily[daily > 0]).dropna().groupby("cell_id").mean()

    dates = pd.to_datetime(cells["date"]).dt.date
    week_rows = cells[in_week(dates)]
    top = week_rows.loc[week_rows.groupby("cell_id")["U"].idxmax()].set_index("cell_id")

    return [
        {
            "cell_id": cid,
            "observed": bool(e > 0),
            "normal": _num(normal.get(cid)) if e > 0 else None,
            "obs_vs_exp": None,  # TODO(P6): y in fuse/cells (contract issue 87)
            "unusual": _num(top["U"].get(cid)),
            "agreement": None if cid not in top.index else int(top.at[cid, "agreement"]),
            "exposure": _num(e),
        }
        for cid, e in weekly.items()
    ]


def basemap(coastline: BaseGeometry) -> dict:
    """GeoJSON in WGS 84. simplify(50) is in metres, so it runs before the conversion."""
    geom = transform(
        coastline.simplify(50),
        lambda xy: np.column_stack(to_wgs84(xy[:, 0], xy[:, 1])),
    )
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": mapping(geom)}],
    }


def data_label(provenance: Iterable[str]) -> str:
    """'simulated', 'real' or 'mixed' from the stage files' provenance; never typed in by hand."""
    kinds = set(provenance)
    if not kinds or not kinds <= {"simulated", "real"}:
        raise ValueError(f"provenance must be non-empty 'simulated'/'real' values, got {kinds}")
    return kinds.pop() if len(kinds) == 1 else "mixed"


def scan_identities(snapshot: dict) -> None:
    """Raise on anything resembling a vessel identifier."""
    hit = _IDENTITY.search(json.dumps(snapshot))
    if hit:
        raise ValueError(f"possible vessel identifier in snapshot: {hit.group(0)!r}")


def _legends(weeks: dict[str, list[dict]]) -> dict:
    """Colour-scale breaks computed here, so the browser only maps a value to a colour.
    Quantile breaks (6 points, 5 bins) over observed values of all shown weeks, so the same colour
    means the same value in every week. Unusual is a fixed 0 to 1; observed versus expected is
    clipped at +-3 (8 times more or less, per the spec)."""
    rows = [r for rs in weeks.values() for r in rs]

    def quantiles(key: str) -> list[float]:
        v = [r[key] for r in rows if r[key] is not None and r["observed"]]
        return (
            sorted({round(float(q), 4) for q in np.quantile(v, np.linspace(0, 1, 6))}) if v else []
        )

    return {
        "normal": {"breaks": quantiles("normal")},
        "obs_vs_exp": {"clip": 3, "breaks": quantiles("obs_vs_exp")},
        "unusual": {"breaks": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]},
        "exposure": {"breaks": quantiles("exposure")},
    }


def _lonlat(x: Any, y: Any) -> dict:
    lon, lat = to_wgs84(x, y)
    return {"lon": round(float(lon), 5), "lat": round(float(lat), 5)}


def _sites(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "id": r["site_id"],
            **_lonlat(r["x_m"], r["y_m"]),
            "S": _num(r["S"]),
            "p_perm": _num(r["p_perm"]),
            "bh_flag": bool(r["bh_flag"]),
            "recurrence": int(r["recurrence"]),
            "agreement": int(r["agreement"]),
            "followup_unobserved": int(r["followup_unobserved"]),
            "reasons": [str(x) for x in r["reasons"]],
            "top_piers": [str(x) for x in r["top_piers"]][:3],
        }
        for r in df.sort_values("S", ascending=False).to_dict("records")
    ]


def _piers(df: pd.DataFrame) -> list[dict]:
    """Road-access piers only. The pier score is in no stage file yet (contract issue 88)."""
    return [
        {
            "id": r["pier_id"],
            "name": r["name"],
            **_lonlat(r["geometry"].x, r["geometry"].y),
            "P_j": None,  # TODO(P6): contract issue 88
        }
        for r in df[df["road_access"]].to_dict("records")
    ]


def _plan(plan: dict) -> dict:
    """Stops get WGS 84 positions for the map; x_m and y_m stay in patrol/plan.json."""
    return {
        asset: [
            {
                "id": s["id"],
                "arrival_utc": s["arrival_utc"],
                "dwell_h": s["dwell_h"],
                **_lonlat(s["x_m"], s["y_m"]),
                **{k: s[k] for k in ("exploration", "not_significant", "stand_in") if k in s},
            }
            for s in stops
        ]
        for asset, stops in plan.items()
    }


def build_snapshot(*, validation_path: Path | None = None) -> dict:
    """Read the stage files and patrol/plan.json, write export/snapshot.json (under the data root)
    through core.io, which checks it with core.schemas.check_json and stamps it."""
    cfg, cfg_hash = load(io.CONFIG_PATH)
    t = io.read_snapshot()["T"]
    f = {n: io.read_stage(n) for n in _INPUTS}

    ref = f["reference/cells"]
    fine = ref[ref["level"] == 2000]
    b = fine.geometry.bounds
    (lon0, lat0), (lon1, lat1) = to_wgs84(b.minx, b.miny), to_wgs84(b.maxx, b.maxy)
    geometry = {
        cid: [round(float(v), 5) for v in box]
        for cid, *box in zip(fine["cell_id"], lon0, lat0, lon1, lat1, strict=True)
    }

    weeks = _weeks(t)
    vpath = (
        validation_path
        or Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "validation.json"
    )
    label = data_label(_provenance(n) for n in _INPUTS)

    cell_weeks = {
        w: heatmap_values(f["forecast/expected"], f["fuse/cells"], f["coverage/exposure"], w)
        for w in weeks
    }
    snap = {
        "meta": {
            "data_label": label,
            "generated_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "region": dict(cfg["region_bbox"]),
            "T": t.isoformat(),
            "week": weeks[-1],
            "weeks": weeks,
            "config_hash": cfg_hash,
        },
        "basemap": basemap(unary_union(list(fine.geometry))),
        "cells": {
            "geometry": geometry,
            "weeks": cell_weeks,
            # Overlay layers (spec: inshore_frac >= 0.1, shipping lanes, exclusion zones)
            "layers": {
                "inshore": list(fine.loc[fine["inshore_frac"] >= 0.1, "cell_id"]),
                "lane": list(fine.loc[fine["lane"], "cell_id"]),
                "exclusion": list(fine.loc[fine["exclusion"], "cell_id"]),
            },
            # Not a top-level key: core.schemas.check_json requires exactly the seven spec keys.
            "legends": _legends(cell_weeks),
        },
        "sites": _sites(f["fuse/sites"]),
        "piers": _piers(f["reference/piers"]),
        "plan": _plan(io.read_json_stage("patrol/plan")),
        "validation": json.loads(vpath.read_text()) if vpath.exists() else None,  # not run yet
    }
    scan_identities(snap)
    # the stamp only decides which config keys make the file stale: a mixed snapshot uses the
    # simulated set, which is a superset of the real one
    io.write_json_stage("export/snapshot", snap, "real" if label == "real" else "simulated")
    return snap


def run() -> None:
    """Entry point for `make all`."""
    build_snapshot()
