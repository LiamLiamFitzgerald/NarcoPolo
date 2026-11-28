"""reference.run on raw/ files (P2's downloads, or the simulator's copies of them): cells, piers, sea travel times
and the three rasters, built only from the P3 functions in this folder. Private: run() writes what build() returns."""

from pathlib import Path
from typing import NamedTuple

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from numpy.typing import NDArray
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from core import io
from core.config import load
from core.crs import to_utm
from core.grid import _origin
from reference import cells as rc
from reference import masks
from reference import piers as rp
from reference.land import land


class Reference(NamedTuple):
    cells: gpd.GeoDataFrame  # 2 km and 10 km rows, reference/cells schema
    piers: gpd.GeoDataFrame
    travel: pd.DataFrame
    rasters: dict[
        str, tuple[NDArray[np.uint8], int]
    ]  # name to (array, pixel_m); rows south to north


def region() -> BaseGeometry:
    """config region_bbox (lon/lat) as a UTM box: the bounds of its four corners."""
    b = load(io.CONFIG_PATH)[0]["region_bbox"]
    x, y = to_utm([b["lon_min"], b["lon_max"]] * 2, [b["lat_min"]] * 2 + [b["lat_max"]] * 2)
    return box(x.min(), y.min(), x.max(), y.max())


def _inshore(raw: Path, cells: gpd.GeoDataFrame) -> pd.Series:
    """inshore_frac from raw/inshore/; NaN everywhere when the maps are missing (no map is not "outside")."""
    grounds, extent = (
        raw / "inshore" / "inshore_grounds.gpkg",
        raw / "inshore" / "survey_extent.gpkg",
    )
    if not (grounds.exists() and extent.exists()):
        return pd.Series(np.nan, index=cells.index, name="inshore_frac")
    ext = gpd.read_file(extent).to_crs(32629).union_all()
    return rc.inshore_frac(cells, gpd.read_file(grounds).to_crs(32629), ext)


def _scenes(raw: Path, limit: int | None) -> list[masks.Scene]:
    """raw/s1 VV in dB on the mask grid (row 0 = south), for the static-object mask."""
    import rasterio

    x0, y0 = _origin()
    out = []
    for tif in sorted((raw / "s1").glob("*.tif"))[:limit]:
        with rasterio.open(tif) as src:
            vv = src.read(1).astype(float) / 100.0  # int16 dB x 100
            xmin, ymax = src.transform.c, src.transform.f
        h = vv.shape[0]
        row0, col0 = round((ymax - h * masks.PX - y0) / masks.PX), round((xmin - x0) / masks.PX)
        out.append(masks.Scene(row0, col0, vv[::-1]))
    return out


def _piers(raw: Path) -> gpd.GeoDataFrame:
    """OSM piers, slipways and harbours. ingest already tags road access (roads within 200 m, P2 spec), so its
    yes/no column is used; without it there is no road data and so no road access (never assumed)."""
    osm = gpd.read_file(raw / "osm_piers.geojson")
    p = rp.piers(osm, gpd.GeoDataFrame(geometry=[], crs=32629))
    if "road_access" in osm.columns and "pier_id" in osm.columns:
        tagged = osm.set_index("pier_id")["road_access"].astype(str).str.lower().eq("yes")
        p["road_access"] = p["pier_id"].map(tagged).fillna(False).astype(bool)
    return p


def build(
    raw: Path | None = None, reg: BaseGeometry | None = None, max_scenes: int | None = None
) -> Reference:
    """reg: the UTM region (default region(); the simulator's coastline only crosses its own smaller box).
    max_scenes: use only the first n scenes for the static mask (tests)."""
    raw = raw or io.raw_root()
    cfg = rc._ref()
    reg = reg if reg is not None else region()
    land_poly = shapely.union_all(
        land(gpd.read_file(raw / "coastline.gpkg"), reg).geometry.to_numpy()
    )
    cells = rc.build_cells(reg, land_poly)
    cells["inshore_frac"] = _inshore(raw, cells).to_numpy()
    p2 = rc.regrid_presence(pd.read_parquet(raw / "gfw_presence.parquet"))
    cells["lane"] = rc.lanes(cells, p2).to_numpy()
    cells["anchorage"] = rc.anchorages(cells, p2).to_numpy()
    osm = gpd.read_file(raw / "osm_piers.geojson").to_crs(32629)
    harbours = osm[osm["harbour"].notna()] if "harbour" in osm.columns else osm.iloc[:0]
    cells["port_zone"] = rc.port_zones(cells, harbours).to_numpy()
    cells["exclusion"] = rc.exclusion(cells["port_zone"], cells["anchorage"]).to_numpy()
    cells["dist_coast_m"] = rc.dist_coast(cells, land_poly).to_numpy()
    land10 = masks.land_mask_10m(land_poly, cfg["coast_buffer_m"])
    static10 = masks.static_mask_10m(
        _scenes(raw, max_scenes), land10, cfg["static_db"], cfg["static_share"], cfg["static_bin_m"],
        cfg["static_window_px"], cfg["static_grow_m"],
    )  # fmt: skip
    cells["static_frac"] = masks.static_frac(cells, static10).to_numpy()
    cells = gpd.GeoDataFrame(pd.concat([cells, rc.to_coarse(cells)], ignore_index=True), crs=32629)
    piers = _piers(raw)
    sea = rp.sea_raster(land_poly, cfg["sea_raster_m"])
    rp.assert_closed(sea)
    travel = rp.travel_hours(sea, piers, cfg["boat_speed_kn"], cfg["sea_raster_m"])
    travel = travel[travel["cell_id"].isin(cells["cell_id"])].reset_index(
        drop=True
    )  # cells layer only
    rasters = {
        "reference/land_mask_10m": (land10, masks.PX),
        "reference/static_mask_10m": (static10, masks.PX),
        "reference/sea_250m": (sea, int(cfg["sea_raster_m"])),
    }
    return Reference(cells, piers, travel, rasters)


def write_raster(name: str, array: NDArray[np.uint8], pixel_m: int) -> Path:
    """A north-up GeoTIFF at core.io.raster_path(name), origin (x0, y0); the array's rows run south to north."""
    import rasterio
    from rasterio.transform import from_origin

    from core.schemas import check_raster

    x0, y0 = _origin()
    check_raster(name, array, pixel_m=pixel_m, origin=(x0, y0))
    path = io.raster_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = array.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=h, width=w, count=1, dtype="uint8", crs="EPSG:32629",
        transform=from_origin(x0, y0 + h * pixel_m, pixel_m, pixel_m), compress="deflate",
    ) as f:  # fmt: skip
        f.write(array[::-1], 1)
    return path
