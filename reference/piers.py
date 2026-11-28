"""Piers, the 250 m sea raster and sea-only travel times from piers to cells (docs/specs/P3.md).

Travel times are shortest paths over sea pixels, 8 directions, diagonal steps sqrt(2) x res: the same cost surface as
skimage's MCP_Geometric, computed with scipy's Dijkstra (scikit-image is not a project dependency). A diagonal step is
allowed only when both pixels it passes between are sea, so a path never slips between two land pixels at a headland.
Thresholds are keyword arguments with the spec's defaults until P3's config keys land (#85)."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from numpy.typing import NDArray
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry.base import BaseGeometry

from core.config import load
from core.crs import to_utm
from core.grid import FINE, _origin, cell_id, cell_index

KN = 0.514444  # m/s per knot (shared.md, Units)
_TAGS = {"man_made": "pier", "leisure": "slipway"}  # plus any harbour=* (spec step 1)


def _corner() -> tuple[float, float]:
    """Top-right corner of region_bbox in UTM (the grid starts at x0, y0)."""
    cfg, _ = load(Path(__file__).resolve().parent.parent / "config.yaml")
    b = cfg["region_bbox"]
    lon, lat = [b["lon_min"], b["lon_max"]] * 2, [b["lat_min"]] * 2 + [b["lat_max"]] * 2
    x, y = to_utm(
        lon, lat
    )  # all four corners: UTM parallels curve, so no single corner holds both maxima
    return float(x.max()), float(y.max())


def _utm(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return g if g.crs is None or g.crs.to_epsg() == 32629 else g.to_crs(32629)


def piers(osm: gpd.GeoDataFrame, roads: gpd.GeoDataFrame, road_m: float = 200) -> gpd.GeoDataFrame:
    """One row per OSM pier (man_made=pier), slipway (leisure=slipway) or harbour (harbour=*); OSM name kept, never
    invented. road_access = a road within road_m. Lines and areas become a point on them."""
    osm = _utm(osm)
    tagged = [c for c in (*_TAGS, "harbour") if c in osm]
    if tagged:
        keep = pd.Series(False, index=osm.index)
        for col, val in _TAGS.items():
            if col in osm:
                keep |= osm[col] == val
        if "harbour" in osm:
            keep |= osm["harbour"].notna()
        osm = osm[keep]
    geom = osm.geometry.where(osm.geom_type == "Point", osm.geometry.representative_point())
    roads = _utm(roads)
    if len(roads):
        near = (geom.distance(roads.union_all()) <= road_m).to_numpy()
    else:
        near = np.zeros(len(osm), bool)  # no road data: no road access, never assumed
    return gpd.GeoDataFrame(
        {
            "pier_id": [f"pier_{i}" for i in range(len(osm))],
            "name": osm["name"].to_numpy() if "name" in osm else None,
            "road_access": near,
        },
        geometry=geom.to_numpy(),
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
    """Raise if two seas that land separates touch only diagonally through it (a leak in the coastline). Flood fill:
    the 8-connected sea must have exactly as many parts as the 4-connected sea."""
    _, four = ndimage.label(sea, structure=ndimage.generate_binary_structure(2, 1))  # pyright: ignore[reportGeneralTypeIssues]
    _, eight = ndimage.label(sea, structure=np.ones((3, 3), int))  # pyright: ignore[reportGeneralTypeIssues]
    if eight != four:
        raise ValueError(
            f"coastline leak: {four - eight} sea region(s) join only diagonally through land; close the coastline"
        )


def _graph(sea: NDArray[np.uint8], res_m: float) -> tuple[coo_matrix, NDArray[np.int64]]:
    """Sea pixels as graph nodes; edges to the right, up, and both upper diagonals (no corner cutting)."""
    h, w = sea.shape
    node = np.full(sea.shape, -1, np.int64)
    s = sea.astype(bool)
    node[s] = np.arange(s.sum())
    rows, cols, cost = [], [], []
    for dr, dc, ok in (
        (0, 1, None),
        (1, 0, None),
        (1, 1, ((1, 0), (0, 1))),
        (1, -1, ((1, 0), (0, -1))),
    ):
        r0, r1 = 0, h - dr
        c0, c1 = max(0, -dc), w - max(0, dc)
        a = s[r0:r1, c0:c1] & s[r0 + dr : r1 + dr, c0 + dc : c1 + dc]
        if ok:
            for orr, oc in ok:
                a &= s[r0 + orr : r1 + orr, c0 + oc : c1 + oc]
        rows.append(node[r0:r1, c0:c1][a])
        cols.append(node[r0 + dr : r1 + dr, c0 + dc : c1 + dc][a])
        cost.append(np.full(a.sum(), res_m * (np.sqrt(2) if dr and dc else 1.0)))
    n = int(s.sum())
    g = coo_matrix(
        (np.concatenate(cost), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)
    )
    return g, node


def travel_hours(
    sea: NDArray[np.uint8], piers: gpd.GeoDataFrame, kn: float = 15, res_m: float = 250
) -> pd.DataFrame:
    """Hours by boat from each road-access pier to each 2 km cell with sea, along sea pixels. Each pier starts from
    its nearest sea pixel (a pier on a land pixel would otherwise start nowhere); each cell is reached at its sea pixel
    nearest the cell centre. Cells a pier cannot reach by sea get no row."""
    x0, y0 = _origin()
    g, node = _graph(sea, res_m)
    r, c = np.nonzero(node >= 0)
    order = node[r, c]
    px, py = np.empty(len(order)), np.empty(len(order))
    px[order], py[order] = x0 + (c + 0.5) * res_m, y0 + (r + 0.5) * res_m
    p = piers[piers["road_access"]]
    starts = [
        int(np.argmin(np.hypot(px - x, py - y)))
        for x, y in zip(p.geometry.x, p.geometry.y, strict=True)
    ]
    dist = dijkstra(g, directed=False, indices=starts) if starts else np.empty((0, len(px)))

    ix, iy = cell_index(px, py, FINE)
    to_centre = np.hypot(px - (x0 + (ix + 0.5) * FINE), py - (y0 + (iy + 0.5) * FINE))
    pix = pd.DataFrame({"ix": ix, "iy": iy, "d": to_centre}).sort_values("d", kind="stable")
    rep = pix.groupby(["ix", "iy"], sort=True).head(1)  # each cell's sea pixel nearest its centre
    ids = [cell_id(int(i), int(j), FINE) for i, j in zip(rep["ix"], rep["iy"], strict=True)]
    hours = dist[:, rep.index.to_numpy()].T / (kn * KN) / 3600  # cells x piers
    out = pd.DataFrame(
        {
            "cell_id": np.repeat(ids, len(p)),
            "pier_id": np.tile(p["pier_id"].to_numpy(), len(ids)),
            "hours": hours.ravel(),
        }
    )
    return out[np.isfinite(out["hours"])].reset_index(drop=True)
