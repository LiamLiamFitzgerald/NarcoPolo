"""Sentinel-1 IW GRD passes and scenes: raw/s1/<hash>.tif (VV, VH int16 dB x 100) + raw/s1/<hash>.json.

list_passes asks the CDSE OData catalogue (openEO has no item search; the STAC host is blocked by our proxy)
and caches its answer as returned under raw/s1_catalogue/<key>.json. One pass = every 25 s slice with the
same platform and absolute orbit. select_passes picks the calm passes from ERA5 plus a few rough ones and
writes every pass, downloaded or not, to raw/s1_passes.json (spec, Resolved ambiguities). fetch_scene runs
one openEO batch job (sigma0-ellipsoid, EPSG:32629 10 m on the region grid) and converts linear sigma0 to
int16 dB x 100: format conversion only. Names not in the spec are TODO(P2) here until P1 moves them to
config `ingest:` (question #261).
"""

import json
import math
import tempfile
import threading
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import pandas as pd
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import shape
from shapely.ops import unary_union

from core.io import raw_root
from ingest import _stub
from ingest.cache import cached, record, request_key

COLLECTION = "SENTINEL1_GRD"  # docs/specs/P2.md pseudo-codebase
COEFFICIENT = "sigma0-ellipsoid"  # docs/specs/P2.md pseudo-codebase
BANDS = ["VV", "VH"]
OPENEO_URL = "https://openeo.dataspace.copernicus.eu"  # TODO(P2): config ingest:, question #261
CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"  # TODO(P2): #261
PRODUCT_TYPE = "IW_GRDH_1S"  # TODO(P2): #261; IW GRD high resolution, dual pol
LICENCE = (  # TODO(P2): #261
    "Copernicus Sentinel data, free and open (Legal Notice on the use of Copernicus Sentinel Data and "
    "Service Information); attribution 'Contains modified Copernicus Sentinel data <year>'"
)
_NODATA = -32768  # int16 minimum: no backscatter (no pass, or outside the swath)
_PX = 10.0  # m, the fixed region grid (issue 5)
_EPSG = 32629
_conn: Any = None
_conn_lock = threading.Lock()  # ingest/run fetches passes in parallel (#33): one login, not N


def list_passes(bbox: _stub.Bbox, start: date, end: date) -> pd.DataFrame:
    """Every IW GRD pass over bbox starting in [start, end] (UTC days):
    pass_id, time, orbit_dir, rel_orbit, footprint (WGS84 WKT), end_time, heading_deg (NaN if one slice)."""
    rows: dict[str, dict] = {}
    for p in _products(bbox, start, end):
        a = {x["Name"]: x["Value"] for x in p["Attributes"]}
        pid = f"S1{a['platformSerialIdentifier']}_{int(a['orbitNumber']):06d}"
        r = rows.setdefault(
            pid,
            {"pass_id": pid, "time": [], "end_time": [], "geoms": [],
             "orbit_dir": a["orbitDirection"], "rel_orbit": int(a["relativeOrbitNumber"])},
        )  # fmt: skip
        r["time"].append(pd.Timestamp(p["ContentDate"]["Start"]))
        r["end_time"].append(pd.Timestamp(p["ContentDate"]["End"]))
        r["geoms"].append(shape(p["GeoFootprint"]))
    out = pd.DataFrame(
        {
            "pass_id": pd.Series([r["pass_id"] for r in rows.values()], dtype="string"),
            "time": pd.Series([min(r["time"]) for r in rows.values()], dtype="datetime64[ns, UTC]"),
            "orbit_dir": pd.Series([r["orbit_dir"] for r in rows.values()], dtype="string"),
            "rel_orbit": pd.Series([r["rel_orbit"] for r in rows.values()], dtype="int64"),
            "footprint": pd.Series(
                [unary_union(r["geoms"]).wkt for r in rows.values()], dtype="string"
            ),
            "end_time": pd.Series(
                [max(r["end_time"]) for r in rows.values()], dtype="datetime64[ns, UTC]"
            ),
            "heading_deg": pd.Series(
                [_heading(r["time"], r["geoms"]) for r in rows.values()], dtype="float64"
            ),
        }
    )
    return out.sort_values("time", ignore_index=True)


def _heading(times: list[pd.Timestamp], geoms: list[Any]) -> float:
    """Platform heading (deg clockwise from north) measured from the pass itself: the WGS84 bearing from the
    first slice's centre to the last's, in acquisition order (#291). NaN for a one-slice pass: unknown."""
    order = sorted(range(len(times)), key=lambda i: times[i])
    first, last = geoms[order[0]].centroid, geoms[order[-1]].centroid
    if len(order) < 2 or times[order[0]] == times[order[-1]] or first.equals(last):
        return math.nan
    az, _, _ = Geod(ellps="WGS84").inv(first.x, first.y, last.x, last.y)
    return float(az) % 360.0


def select_passes(passes: pd.DataFrame, era5: Path) -> pd.DataFrame:
    """passes + calm_share + downloaded: a pass is downloaded if >= s1_calm_share of the ERA5 sea points it
    covers inside the region are calm at the nearest hour, plus s1_rough_passes rough ones spread over time."""
    cfg = _stub.config()
    cov, ing = cfg["coverage"], cfg["ingest"]
    lon0, lat0, lon1, lat1 = _stub.region(cfg)
    with netCDF4.Dataset(era5) as nc:
        t = nc.variables["valid_time" if "valid_time" in nc.variables else "time"]
        stamps: Any = netCDF4.num2date(t[:], t.units)
        hours = pd.DatetimeIndex([pd.Timestamp(str(d), tz="UTC") for d in np.asarray(stamps)])
        lat = np.asarray(nc.variables["latitude"][:], dtype=float)
        lon = np.asarray(nc.variables["longitude"][:], dtype=float)
        u, v, hs = (
            np.ma.filled(np.ma.asarray(nc.variables[n][:], float), np.nan)
            for n in ("u10", "v10", "swh")
        )
    lon2, lat2 = np.meshgrid(lon, lat)
    in_region = (lon2 >= lon0) & (lon2 <= lon1) & (lat2 >= lat0) & (lat2 <= lat1)
    calm = (np.hypot(u, v) < cov["calm_wind_ms"]) & (hs < cov["calm_hs_m"])
    shares = []
    for time, footprint in zip(passes["time"].tolist(), passes["footprint"].tolist(), strict=True):
        when = pd.Timestamp(time)
        k = int(np.abs((hours - when).total_seconds()).argmin()) if len(hours) else -1
        if k < 0 or abs((hours[k] - when).total_seconds()) > 1800:
            shares.append(math.nan)  # no ERA5 hour for this pass: unknown, never calm or rough
            continue
        sea = in_region & shapely.contains_xy(shapely.from_wkt(str(footprint)), lon2, lat2)
        sea &= ~np.isnan(hs[k])  # no wave value = land point
        shares.append(float(calm[k][sea].mean()) if sea.any() else math.nan)
    share = pd.Series(shares, index=passes.index, dtype=float)
    down = (share >= ing["s1_calm_share"]).to_numpy(copy=True)
    rough = np.flatnonzero(share.notna().to_numpy() & ~down)
    n = int(ing["s1_rough_passes"])
    if len(rough) > n:  # the first, the last and evenly spaced ones between
        rough = rough[np.unique(np.round(np.linspace(0, len(rough) - 1, n)).astype(int))]
    down[rough] = True
    out = passes.assign(calm_share=share, downloaded=down)
    _write_passes(out)
    return out


def fetch_scene(pass_: Mapping[str, Any]) -> Path:
    """One row of list_passes (`pass` is a Python keyword) -> raw/s1/<hash>.tif and .json; returns the .tif."""
    cfg = _stub.config()
    # whole seconds, "Z": the openEO client rejects fractional seconds and offsets
    start = pd.Timestamp(pass_["time"]).tz_convert("UTC").floor("s")
    stop = pd.Timestamp(pass_["end_time"]).tz_convert("UTC").ceil("s") + pd.Timedelta(seconds=1)
    utc = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    extent = _extent(_stub.region(cfg), float(cfg["x0"]), float(cfg["y0"]))
    req = {
        "source": "s1", "collection": COLLECTION, "coefficient": COEFFICIENT, "bands": BANDS,
        "pass_id": str(pass_["pass_id"]), "start": utc(start), "end": utc(stop),
        "extent": extent, "crs": _EPSG, "px": _PX,
    }  # fmt: skip
    if (hit := cached(req)) is not None:
        return hit
    key = request_key(req)
    path = raw_root() / "s1" / f"{key}.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    cube = _connection().load_collection(
        COLLECTION,
        spatial_extent=dict(zip(("west", "south", "east", "north"), extent, strict=True))
        | {"crs": _EPSG},
        temporal_extent=[utc(start), utc(stop)],  # end exclusive
        bands=BANDS,
    )
    cube = cube.sar_backscatter(coefficient=COEFFICIENT)
    cube = cube.resample_spatial(resolution=_PX, projection=_EPSG)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        linear = Path(tmp) / "sigma0.tif"
        cube.execute_batch(outputfile=linear, out_format="GTiff", title=f"s1 {pass_['pass_id']}")
        _to_db100(linear, path, float(cfg["x0"]), float(cfg["y0"]))
    meta = {
        "scene_id": key,
        "pass_id": str(pass_["pass_id"]),
        "start_time": pd.Timestamp(pass_["time"]).tz_convert("UTC").isoformat(),
        "orbit_direction": str(pass_["orbit_dir"]),
        "relative_orbit": int(pass_["rel_orbit"]),
        "footprint": str(pass_["footprint"]),
        "footprint_crs": "EPSG:4326",
        # openEO gives no annotation metadata (issue 6); heading is measured from the pass instead
        "incidence_min": None,
        "incidence_max": None,
        "prf_hz": None,
        "slant_range_m": None,
        "satellite_speed_ms": None,
        "heading_deg": _float_or_none(pass_.get("heading_deg")),  # measured from the slices (#291)
    }
    meta_path = path.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=1))
    record(req, path, LICENCE)
    record({**req, "part": "metadata"}, meta_path, LICENCE)
    return path


def _float_or_none(v: Any) -> float | None:
    """A finite number rounded to 0.01, else None (unknown stays null in the metadata, never 0)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if math.isfinite(f) else None


def _catalogue(url: str, params: dict | None) -> dict:
    """One catalogue GET; the seam offline tests replace."""
    import requests  # installed with openeo

    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _products(bbox: _stub.Bbox, start: date, end: date) -> list[dict]:
    """Catalogue products as returned, cached under raw/s1_catalogue/<key>.json."""
    lon0, lat0, lon1, lat1 = (float(v) for v in bbox)
    ring = f"{lon0} {lat0},{lon1} {lat0},{lon1} {lat1},{lon0} {lat1},{lon0} {lat0}"
    stop = end + timedelta(days=1)  # our windows are inclusive
    flt = (
        "Collection/Name eq 'SENTINEL-1' and Attributes/OData.CSC.StringAttribute/any("
        f"att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{PRODUCT_TYPE}') "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;POLYGON(({ring}))') "
        f"and ContentDate/Start ge {start.isoformat()}T00:00:00.000Z "
        f"and ContentDate/Start lt {stop.isoformat()}T00:00:00.000Z"
    )
    params = {
        "$filter": flt,
        "$expand": "Attributes",
        "$top": 1000,
        "$orderby": "ContentDate/Start asc",
    }
    req = {"source": "s1_catalogue", "url": CATALOGUE_URL, "params": params}
    if (hit := cached(req)) is not None:
        return json.loads(hit.read_text())
    products, url, query = [], CATALOGUE_URL, params
    while url:
        page = _catalogue(url, query)
        products += page["value"]
        url, query = page.get("@odata.nextLink"), None  # the next link carries the query
    path = raw_root() / "s1_catalogue" / f"{request_key(req)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(products))
    record(req, path, LICENCE)
    return products


def _write_passes(out: pd.DataFrame) -> None:
    """raw/s1_passes.json: every pass in the window with its downloaded flag; rewritten only on change."""
    rows = [
        {
            "pass_id": str(r["pass_id"]), "time": pd.Timestamp(r["time"]).isoformat(),
            "orbit_dir": str(r["orbit_dir"]), "rel_orbit": int(r["rel_orbit"]),
            "footprint": str(r["footprint"]),
            "calm_share": None if math.isnan(r["calm_share"]) else float(r["calm_share"]),
            "downloaded": bool(r["downloaded"]),
        }
        for r in out.to_dict("records")
    ]  # fmt: skip
    text = json.dumps(rows, indent=1)
    path = raw_root() / "s1_passes.json"
    if path.is_file() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    record({"source": "s1_passes", "pass_ids": [r["pass_id"] for r in rows]}, path, LICENCE)


def _extent(bbox: _stub.Bbox, x0: float, y0: float) -> list[float]:
    """bbox's EPSG:32629 envelope, snapped outward onto the 10 m grid from (x0, y0)."""
    w, s, e, n = Transformer.from_crs(4326, _EPSG, always_xy=True).transform_bounds(*bbox)
    snap = lambda v, o, f: o + f((v - o) / _PX) * _PX
    return [
        snap(w, x0, math.floor),
        snap(s, y0, math.floor),
        snap(e, x0, math.ceil),
        snap(n, y0, math.ceil),
    ]


def _connection() -> Any:
    """openEO on Copernicus Data Space, OIDC device login; no refresh token is written to disk."""
    global _conn
    with _conn_lock:  # threads that arrive during the device login wait for it, then share it
        if _conn is None:
            import openeo

            _conn = openeo.connect(OPENEO_URL).authenticate_oidc(store_refresh_token=False)
        return _conn


def _to_db100(src: Path, dst: Path, x0: float, y0: float) -> None:
    """Linear sigma0 GeoTIFF -> int16 dB x 100 on the same grid; fails if openEO's grid is not ours."""
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(src) as r:
        t = r.transform
        ok = (
            r.crs is not None and r.crs.to_epsg() == _EPSG and r.count == 2
            and (t.a, t.e, t.b, t.d) == (_PX, -_PX, 0.0, 0.0)
            and (t.c - x0) % _PX == 0 and (t.f - y0) % _PX == 0
        )  # fmt: skip
        if not ok:
            raise ValueError(
                f"openEO grid is not EPSG:{_EPSG} {_PX} m from (x0, y0): {r.crs} {t} {r.count} bands"
            )
        if any(d is not None for d in r.descriptions) and list(r.descriptions) != BANDS:
            raise ValueError(f"band order {r.descriptions}, expected {BANDS}")
        profile = {
            "driver": "GTiff", "width": r.width, "height": r.height, "count": 2, "dtype": "int16",
            "crs": r.crs, "transform": t, "nodata": _NODATA,
        }  # fmt: skip
        with rasterio.open(dst, "w", **profile) as w:
            w.descriptions = tuple(BANDS)
            step = 512
            for row in range(0, r.height, step):
                win = Window(0, row, r.width, min(step, r.height - row))  # pyright: ignore[reportCallIssue]
                lin = r.read(window=win, masked=True).astype(np.float64).filled(np.nan)
                with np.errstate(divide="ignore", invalid="ignore"):
                    db = np.round(1000.0 * np.log10(lin))  # 10 log10 * 100
                good = np.isfinite(db)
                out = np.full(db.shape, _NODATA, dtype=np.int16)
                out[good] = np.clip(db[good], _NODATA + 1, 32767).astype(np.int16)
                w.write(out, window=win)
