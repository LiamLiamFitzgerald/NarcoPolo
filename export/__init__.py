"""Snapshot export (P7): freeze the plan, heat maps, sites, piers and validation into one JSON file.
The dashboard only draws what is written here (docs/specs/P7.md)."""

import base64
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
    "fuse/piers",
    "fuse/links",
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
    ratio     the week's y_week itself, for plain-language phrasing (#315)
    obs_vs_exp  log2 of the week's y_week = (sum C + 0.5) / (sum mu + 0.5) for dark_small (fuse/cells, #87)
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
    small_rows = week_rows[week_rows["event_type"] == "dark_small"]
    # y_week is the same on every observed day of a cell's week (P6); a cell with no dark_small row has none
    y_week = (
        small_rows.groupby("cell_id")["y_week"].first()
        if "y_week" in small_rows.columns
        else pd.Series(dtype=float)
    )

    return [
        {
            "cell_id": cid,
            "observed": bool(e > 0),
            "normal": _num(normal.get(cid)) if e > 0 else None,
            "obs_vs_exp": _num(np.log2(y_week[cid])) if cid in y_week.index else None,
            # the same value as a plain ratio, for "about 2x more small boats than normal" (#315)
            "ratio": _num(y_week[cid]) if cid in y_week.index else None,
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


def _basemap(study_area: BaseGeometry, land: BaseGeometry | None) -> dict:
    """The study-area outline, and the land (#133) when reference/land exists: on real data that is the
    real coast of Ireland from the OSM coastline; the simulator writes a straight one."""
    fc = basemap(study_area)
    fc["features"][0]["properties"] = {"kind": "study_area"}
    if land is not None:
        fc["features"].append({**basemap(land)["features"][0], "properties": {"kind": "land"}})
    return fc


def _read_land() -> BaseGeometry | None:
    try:
        return unary_union(list(io.read_stage("reference/land").geometry))
    except ValueError:  # the layer is optional (#133): no stamp means no land layer was written
        return None


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


def _scan(snapshot: dict) -> None:
    """scan_identities on everything but the backdrop's pixels: base64 is not text, and a 9-digit run
    can appear in it by chance. Its bounds and attribution are still scanned."""
    bd = snapshot.get("basemap", {}).get("backdrop")
    if bd:
        snapshot = {**snapshot, "basemap": {**snapshot["basemap"], "backdrop": {**bd, "image": ""}}}
    scan_identities(snapshot)


_PNG = b"\x89PNG\r\n\x1a\n"
_BACKDROP_MAX = 1_000_000  # bytes (contract #263); the snapshot must stay under 5 MB


def _backdrop(png: bytes, meta: dict) -> dict:
    """The Sentinel-1 radar backdrop as a data URI the dashboard can draw offline."""
    if not png.startswith(_PNG):
        raise ValueError("radar backdrop is not a PNG")
    if len(png) > _BACKDROP_MAX:
        raise ValueError("radar backdrop is over 1 MB")
    if len(meta.get("bounds", [])) != 4:
        raise ValueError("radar backdrop needs bounds [lon_min, lat_min, lon_max, lat_max]")
    return {
        "image": "data:image/png;base64," + base64.b64encode(png).decode(),
        "bounds": [float(v) for v in meta["bounds"]],
        "attribution": str(meta.get("attribution", "Contains modified Copernicus Sentinel data")),
        "from": meta.get("from"),
        "to": meta.get("to"),
    }


def _read_backdrop(t: date | None = None) -> dict | None:
    """reference/radar_backdrop.png and .json if P3 has written them (contract #263); else the composite of
    the Sentinel-1 scenes in raw/s1 up to T (#387); else None.
    shortcut: reads P3's files directly; switch to the core.io reader once P1 adds it in #263."""
    ref = io.stage_path("reference/cells").parent
    png, meta = ref / "radar_backdrop.png", ref / "radar_backdrop.json"
    if png.exists() and meta.exists():
        return _backdrop(png.read_bytes(), json.loads(meta.read_text()))
    made = _raw_backdrop(io.raw_root(), t) if t is not None else None
    return _backdrop(*made) if made else None


# Display settings for the raw/s1 composite (#387): how it looks, not a statistic. TODO(P7) #387: confirm.
_BACKDROP_WIDTH_PX = 1600  # widest image; halved until the PNG fits _BACKDROP_MAX
_STRETCH_PCT = (
    2,
    98,
)  # grey runs from these percentiles of the shown VV values (dB), clipped beyond


def _scenes(root: Path, t: date) -> list[tuple[pd.Timestamp, Path]]:
    """raw/s1/<id>.tif with their start times, up to T (never a scene after the snapshot date), oldest first."""
    out = []
    for meta in sorted((root / "s1").glob("*.json")):
        when = pd.Timestamp(json.loads(meta.read_text())["start_time"])
        if when.date() <= t and meta.with_suffix(".tif").exists():
            out.append((when, meta.with_suffix(".tif")))
    return sorted(out, key=lambda x: x[0])


def _attribution(root: Path, scenes: list[tuple[pd.Timestamp, Path]]) -> str:
    """From raw/manifest.json: simulated scenes say so; real ones carry the Copernicus credit."""
    files = (
        json.loads((root / "manifest.json").read_text()).get("files", {})
        if (root / "manifest.json").exists()
        else {}
    )
    sim = [
        files.get(f"s1/{p.name}", {}).get("request", {}).get("simulated") is True for _, p in scenes
    ]
    if all(sim):
        return "Simulated radar image from the simulator: not real satellite data"
    return f"Contains modified Copernicus Sentinel data {scenes[-1][0].year}"


def _raw_backdrop(root: Path, t: date) -> tuple[bytes, dict] | None:
    """The VV band of every scene up to T, reprojected to WGS 84 over the scenes' joint footprint; the latest
    scene wins per pixel. Pixels no scene covered are transparent, never black (Design principle 4).
    Grey PNG with an alpha band, at most _BACKDROP_WIDTH_PX wide and under _BACKDROP_MAX bytes."""
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds

    scenes = _scenes(root, t)
    if not scenes:
        return None
    srcs = [rasterio.open(p) for _, p in scenes]
    try:
        crs = srcs[0].crs
        if any(s.crs != crs for s in srcs):
            raise ValueError("raw/s1 scenes are not all on one grid CRS")
        b = [s.bounds for s in srcs]
        utm = (
            min(x.left for x in b),
            min(x.bottom for x in b),
            max(x.right for x in b),
            max(x.top for x in b),
        )
        lon0, lat0, lon1, lat1 = transform_bounds(crs, "EPSG:4326", *utm)
        width = min(_BACKDROP_WIDTH_PX, round((utm[2] - utm[0]) / srcs[0].res[0]))
        while True:
            height = max(1, round(width * (utm[3] - utm[1]) / (utm[2] - utm[0])))
            dst = from_bounds(lon0, lat0, lon1, lat1, width, height)
            vv = np.full((height, width), np.nan, np.float32)
            for s in srcs:  # oldest first, so a later scene overwrites
                tmp = np.full_like(vv, np.nan)
                reproject(
                    s.read(1).astype(np.float32), tmp, src_transform=s.transform, src_crs=crs,
                    src_nodata=s.nodata, dst_transform=dst, dst_crs="EPSG:4326", dst_nodata=np.nan,
                    resampling=Resampling.average,
                )  # fmt: skip
                vv = np.where(np.isfinite(tmp), tmp, vv)
            seen = np.isfinite(vv)
            lo, hi = np.percentile(vv[seen], _STRETCH_PCT)
            grey = np.clip((np.nan_to_num(vv, nan=lo) - lo) / max(hi - lo, 1e-9) * 255, 0, 255)
            with MemoryFile() as mem:
                with mem.open(
                    driver="PNG", width=width, height=height, count=2, dtype="uint8",
                    transform=dst, crs="EPSG:4326",
                ) as out:  # fmt: skip
                    out.write(np.stack([grey.astype(np.uint8), seen.astype(np.uint8) * 255]))
                png = mem.read()
            if len(png) <= _BACKDROP_MAX or width <= 64:
                break
            width //= 2
    finally:
        for s in srcs:
            s.close()
    meta = {
        "bounds": [lon0, lat0, lon1, lat1],
        "attribution": _attribution(root, scenes),
        "from": scenes[0][0].date().isoformat(),
        "to": scenes[-1][0].date().isoformat(),
    }
    return png, meta


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


_UNUSUAL_U = (
    0.9  # the spec's "U >= 0.9" agreement threshold, reused for the daily count of unusual cells
)
_HALF_LIFE_D = 30  # S is the sum of L with a 30-day half-life (docs/shared.md, Measures)


def _links(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Per site, the link scores behind S, oldest first, each with its decayed weight (they add up to S)."""
    out: dict[str, list[dict]] = {}
    for r in df.sort_values("age_days", ascending=False).to_dict("records"):
        w = float(r["L"]) * 0.5 ** (float(r["age_days"]) / _HALF_LIFE_D)
        out.setdefault(str(r["site_id"]), []).append(
            {"age_days": _num(r["age_days"]), "L": _num(r["L"]), "weight": _num(w)}
        )
    return out


# The briefing card's three evidence checks (#314). PLACEHOLDER (#320): P6 has not written these yet, so
# the column names below are our guess at the contract and every check reads None ("not available yet")
# until fuse/sites carries them. The browser never derives a check.
_CHECKS = (
    (
        "rare_slowdown",
        "check_rare_slowdown",
    ),  # TODO(P7) #320: a ship slowed where ships rarely slow
    ("boats_after", "check_boats_after"),  # TODO(P7) #320: small boats seen afterwards nearby
    ("outside_fishing", "check_outside_fishing"),  # TODO(P7) #320: outside normal fishing activity
)


def _flag_or_none(v: Any) -> bool | None:
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else bool(v)


def _timeline(
    links: pd.DataFrame, exposure: pd.DataFrame, t: date, start: date, link_days: int
) -> dict[str, list[dict]]:
    """Per site, each ship slowdown since `start` (oldest first) with the radar passes over the site's
    2 km cell in the `link_days` after it. A pass is "calm" (small boats visible) or "rough" (small boats
    unobserved). Whether a small boat was seen on a pass needs detect events (#320), so `seen` is None:
    never False, because nobody has looked it up (Design principle 4)."""
    ages = links.assign(day=[t - timedelta(days=int(a)) for a in links["age_days"]])
    ages = ages[ages["day"] >= start]
    ex = exposure[exposure["cell_id"].isin(set(ages["site_id"])) & (exposure["covered_frac"] > 0)]
    ex = ex.assign(day=ex["time_utc"].dt.date).sort_values("time_utc")
    by_cell = {c: g for c, g in ex.groupby("cell_id")}
    out: dict[str, list[dict]] = {}
    for r in ages.sort_values("day").to_dict("records"):
        g = by_cell.get(r["site_id"])
        after = (
            g[(g["day"] >= r["day"]) & (g["day"] <= r["day"] + timedelta(days=link_days))]
            if g is not None
            else g
        )
        out.setdefault(str(r["site_id"]), []).append(
            {
                "date": r["day"].isoformat(),
                "L": _num(r["L"]),
                "passes": []
                if after is None
                else [
                    {
                        "date": p["day"].isoformat(),
                        "state": "calm" if p["exposure_small"] > 0 else "rough",
                        "seen": None,  # PLACEHOLDER (#320): needs detect events per pass
                    }
                    for p in after.to_dict("records")
                ],
            }
        )
    return out


def _daily(
    cells: pd.DataFrame, exposure: pd.DataFrame, fine_ids: list[str], days: list[date]
) -> list[dict]:
    """Per day, for the charts: radar passes, share of the 2 km sea cells covered at all and on calm passes
    (usable for small boats), and the number of cells rated unusual (U >= 0.9) and flagged. A day with no
    pass, or no scored cells, gets None, never 0 (Design principle 4)."""
    n = len(fine_ids)
    ex = exposure[exposure["cell_id"].isin(fine_ids)]
    ex = ex.assign(day=ex["time_utc"].dt.date)
    fz = cells.assign(day=pd.to_datetime(cells["date"]).dt.date)
    out = []
    for d in days:
        e, c = ex[ex["day"] == d], fz[fz["day"] == d]
        passes = int(e["pass_id"].nunique())
        out.append(
            {
                "date": d.isoformat(),
                "passes": passes,
                "covered_share": _num(e.loc[e["covered_frac"] > 0, "cell_id"].nunique() / n)
                if passes
                else None,
                "calm_share": _num(e.loc[e["exposure_small"] > 0, "cell_id"].nunique() / n)
                if passes
                else None,
                "unusual_cells": int(c.loc[c["U"] >= _UNUSUAL_U, "cell_id"].nunique())
                if len(c)
                else None,
                "flagged_cells": int(c.loc[c["bh_flag"], "cell_id"].nunique()) if len(c) else None,
            }
        )
    return out


def _hours(stops: list[dict]) -> float | None:
    if len(stops) < 2:
        return None
    span = pd.Timestamp(stops[-1]["arrival_utc"]) - pd.Timestamp(stops[0]["arrival_utc"])
    return _num(span.total_seconds() / 3600)


def _figures(sites: list[dict], week_rows: list[dict], plan: dict, cfg: Any) -> dict:
    """Headline numbers for the dashboard's figures strip, so the browser computes none of them."""
    p = cfg.get("patrol", {})
    return {
        "sites": len(sites),
        "flagged": sum(s["bh_flag"] for s in sites),
        "candidates": min(int(p.get("top_sites", 15)), len(sites)),
        "ship_h": _hours(plan.get("ship", [])),
        "ship_budget_h": float(p.get("ship_budget_h", 24)),  # spec defaults
        "aircraft_h": _hours(plan.get("aircraft", [])),
        "aircraft_budget_h": float(p.get("aircraft_budget_h", 4)),
        "observed_share": _num(sum(r["observed"] for r in week_rows) / len(week_rows))
        if week_rows
        else None,
    }


def _sites(
    df: pd.DataFrame,
    links: dict[str, list[dict]] | None = None,
    timeline: dict[str, list[dict]] | None = None,
) -> list[dict]:
    links, timeline = links or {}, timeline or {}
    return [
        {
            "id": r["site_id"],
            **_lonlat(r["x_m"], r["y_m"]),
            "S": _num(r["S"]),
            "p_perm": _num(r["p_perm"]),
            "bh_flag": bool(r["bh_flag"]),
            "recurrence": int(r["recurrence"]),
            "agreement": int(r["agreement"]),
            # D1 (#176): what the dashboard shows; the raw 0-4 count double-counts detectors that share counts
            "agreement_merged": None
            if pd.isna(r.get("agreement_merged"))
            else int(r["agreement_merged"]),
            "followup_unobserved": int(r["followup_unobserved"]),
            # D1 (#176): the dashboard ranks sites by p_site; None where the site model gave none
            "p_site": _num(r.get("p_site")),
            "links": links.get(str(r["site_id"]), []),
            # the briefing lens that put the site here (#313): every site P6 writes today is a drop-off
            # site; a `lens` column from P6 (fisheries, #321) takes over when it exists
            "lens": str(r["lens"]) if "lens" in r and isinstance(r["lens"], str) else "dropoff",
            "reasons": [str(x) for x in r["reasons"]],
            "top_piers": [str(x) for x in r["top_piers"]][:3],
            # PLACEHOLDER (#320): sea travel minutes to each top pier, from P6; None until it exists
            "top_pier_minutes": [_num(x) for x in r["top_pier_minutes"]][:3]
            if isinstance(r.get("top_pier_minutes"), list | tuple | np.ndarray)
            else [None] * min(3, len(r["top_piers"])),
            "checks": {k: _flag_or_none(r.get(col)) for k, col in _CHECKS},
            "timeline": timeline.get(str(r["site_id"]), []),
        }
        for r in df.sort_values("S", ascending=False).to_dict("records")
    ]


def _piers(df: pd.DataFrame, scores: pd.DataFrame) -> list[dict]:
    """Road-access piers only, with the pier score P_j from fuse/piers (#88); None if P6 gave it none."""
    pj = scores.set_index("pier_id")["P_j"]
    return [
        {
            "id": r["pier_id"],
            "name": r["name"],
            **_lonlat(r["geometry"].x, r["geometry"].y),
            "P_j": _num(pj.get(r["pier_id"])),
        }
        for r in df[df["road_access"]].to_dict("records")
    ]


def _mission_mix(cfg: Any) -> dict:
    """The mission-mix slider (#316). PLACEHOLDER: only the 0 % fisheries plan exists, because fisheries
    candidates (#321) and the `patrol.mission_mixes` presets (TODO(P7), P1 to add to config.yaml) do not.
    `wanted` lists the presets the slider will offer; `ready` the mixes with a plan in `plan` today."""
    wanted = cfg.get("patrol", {}).get("mission_mixes")
    return {"wanted": [int(m) for m in wanted] if wanted else [0], "ready": [0]}


def _plan(plan: dict, lens: dict[str, str] | None = None) -> dict:
    """Stops get WGS 84 positions for the map (x_m and y_m stay in patrol/plan.json) and `at_h`, hours
    from the asset's first stop, so the schedule chart needs no date arithmetic in the browser. A stop at
    a site also gets the lens that put the site on the shortlist (#316); the base gets none."""
    lens = lens or {}
    t0 = {a: pd.Timestamp(st[0]["arrival_utc"]) for a, st in plan.items() if st}
    return {
        asset: [
            {
                "id": s["id"],
                "arrival_utc": s["arrival_utc"],
                "at_h": _num((pd.Timestamp(s["arrival_utc"]) - t0[asset]).total_seconds() / 3600),
                "dwell_h": s["dwell_h"],
                **_lonlat(s["x_m"], s["y_m"]),
                **({"lens": lens[s["id"]]} if s["id"] in lens else {}),
                **{
                    k: s[k]
                    for k in ("exploration", "not_significant", "stand_in", "reason")
                    if k in s
                },
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

    year, wk = weeks[0].split("-W")
    first = date.fromisocalendar(int(year), int(wk), 1)
    sites = _sites(
        f["fuse/sites"],
        _links(f["fuse/links"]),
        _timeline(f["fuse/links"], f["coverage/exposure"], t, first, int(cfg["p6"]["link_days"])),
    )
    plan = _plan(io.read_json_stage("patrol/plan"), {s["id"]: s["lens"] for s in sites})
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
            "top_sites": int(cfg.get("patrol", {}).get("top_sites", 15)),  # the spec's default
            "figures": _figures(sites, cell_weeks[weeks[-1]], plan, cfg),
            "mission_mix": _mission_mix(cfg),
            "week": weeks[-1],
            "weeks": weeks,
            "config_hash": cfg_hash,
        },
        "basemap": {
            **_basemap(unary_union(list(fine.geometry)), _read_land()),
            # a GeoJSON foreign member, so the snapshot keeps exactly its seven top-level keys
            **({"backdrop": bd} if (bd := _read_backdrop(t)) else {}),
        },
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
            # per day from the first shown Monday to T, for the trend and coverage charts
            "daily": _daily(
                f["fuse/cells"],
                f["coverage/exposure"],
                list(fine["cell_id"]),
                [first + timedelta(days=k) for k in range((t - first).days + 1)],
            ),
        },
        "sites": sites,
        "piers": _piers(f["reference/piers"], f["fuse/piers"]),
        "plan": plan,
        "validation": json.loads(vpath.read_text()) if vpath.exists() else None,  # not run yet
    }
    _scan(snap)
    # the stamp only decides which config keys make the file stale: a mixed snapshot uses the
    # simulated set, which is a superset of the real one
    io.write_json_stage("export/snapshot", snap, "real" if label == "real" else "simulated")
    return snap


def run() -> None:
    """Entry point for `make all`."""
    build_snapshot()
