"""Piers, the 250 m sea raster and sea-only travel times from piers to cells (docs/specs/P3.md).
Stubs (#22): straight-line travel times; the minimum-cost path around headlands comes in #36."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from numpy.typing import NDArray
from shapely.geometry.base import BaseGeometry

from core.config import load
from core.crs import to_utm
from core.grid import FINE, _origin, cell_id, cell_index

KN = 0.514444  # m/s per knot (shared.md, Units)
_RES_M = 250  # shortcut: travel_hours assumes sea_raster's default resolution; #36 passes the grid with the raster


def _corner() -> tuple[float, float]:
    """Top-right corner of region_bbox in UTM (the grid starts at x0, y0)."""
    cfg, _ = load(Path(__file__).resolve().parent.parent / "config.yaml")
    b = cfg["region_bbox"]
    lon, lat = [b["lon_min"], b["lon_max"]] * 2, [b["lat_min"]] * 2 + [b["lat_max"]] * 2
    x, y = to_utm(
        lon, lat
    )  # all four corners: UTM parallels curve, so no single corner holds both maxima
    return float(x.max()), float(y.max())


def piers(osm: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One row per OSM pier, slipway or harbour; the OSM name kept, never invented."""
    return gpd.GeoDataFrame(
        {
            "pier_id": [f"pier_{i}" for i in range(len(osm))],
            "name": osm["name"].to_numpy() if "name" in osm else None,
            "road_access": True,  # stub: #36 checks a road within the configured distance
        },
        geometry=osm.geometry.to_numpy(),
        crs=32629,
    )


def sea_raster(coastline: BaseGeometry, res_m: float = 250) -> NDArray[np.uint8]:
    """1 = sea, 0 = land, over region_bbox; pixel (r, c) has centre (x0 + (c + .5) res, y0 + (r + .5) res)."""
    x0, y0 = _origin()
    xmax, ymax = _corner()
    xs = x0 + (np.arange(int(np.ceil((xmax - x0) / res_m))) + 0.5) * res_m
    ys = y0 + (np.arange(int(np.ceil((ymax - y0) / res_m))) + 0.5) * res_m
    xx, yy = np.meshgrid(xs, ys)
    return (~shapely.contains_xy(coastline, xx, yy)).astype(np.uint8)


def assert_closed(sea: NDArray[np.uint8]) -> None:
    """Raise if the coastline leaks (flood-fill check)."""
    # stub: #36


def travel_hours(sea: NDArray[np.uint8], piers: gpd.GeoDataFrame, kn: float = 15) -> pd.DataFrame:
    """Hours by boat from each road-access pier to each 2 km cell with sea."""
    x0, y0 = _origin()
    r, c = np.nonzero(sea)
    ix, iy = cell_index(x0 + (c + 0.5) * _RES_M, y0 + (r + 0.5) * _RES_M, FINE)
    cells = sorted(set(zip(ix.tolist(), iy.tolist(), strict=True)))
    cx = np.array([x0 + (i + 0.5) * FINE for i, _ in cells])
    cy = np.array([y0 + (j + 0.5) * FINE for _, j in cells])
    p = piers[piers["road_access"]]
    # stub: straight line; #36 uses MCP_Geometric on the sea raster
    d = np.hypot(cx[:, None] - p.geometry.x.to_numpy(), cy[:, None] - p.geometry.y.to_numpy())
    return pd.DataFrame(
        {
            "cell_id": np.repeat([cell_id(i, j, FINE) for i, j in cells], len(p)),
            "pier_id": np.tile(p["pier_id"].to_numpy(), len(cells)),
            "hours": (d / (kn * KN) / 3600).ravel(),
        }
    )
