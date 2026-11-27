"""2 km cells and their static layers (docs/specs/P3.md). Every series is indexed by cell_id, like build_cells' output.

Thresholds are keyword arguments with the spec's defaults until P3's config keys land (#85)."""

import re

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from core.crs import to_utm
from core.grid import COARSE, FINE, _origin, cell_id, parent

_PRESENCE_COLS = ["cell_id", "date", "vessel_type", "speed_bin", "hours"]
_FISHING = "fishing"  # GFW vessel_type of fishing vessels; lanes count every other type


def _grid(bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Every 2 km cell of the core grid that touches `bounds`, indexed by cell_id."""
    x0, y0 = _origin()
    xmin, ymin, xmax, ymax = bounds
    ix = np.arange(int((xmin - x0) // FINE), int(np.ceil((xmax - x0) / FINE)))
    iy = np.arange(int((ymin - y0) // FINE), int(np.ceil((ymax - y0) / FINE)))
    ii, jj = (a.ravel() for a in np.meshgrid(ix, iy, indexing="ij"))
    ids = [cell_id(int(i), int(j), FINE) for i, j in zip(ii, jj, strict=True)]
    geom = [
        box(x0 + i * FINE, y0 + j * FINE, x0 + (i + 1) * FINE, y0 + (j + 1) * FINE)
        for i, j in zip(ii, jj, strict=True)
    ]
    return gpd.GeoDataFrame({"cell_id": ids}, geometry=geom, crs=32629, index=pd.Index(ids))


def build_cells(
    region: BaseGeometry, coastline: BaseGeometry, min_sea_frac: float = 0.2
) -> gpd.GeoDataFrame:
    """2 km cells of `region` (UTM polygon) with sea_frac = sea area / full cell area; keeps sea_frac >= min_sea_frac.
    `coastline` is the land polygon."""
    g = _grid(region.bounds)
    sea = region.difference(coastline)
    g["sea_frac"] = g.intersection(sea).area / (FINE * FINE)
    g = g[g["sea_frac"] >= min_sea_frac - 1e-9].copy()
    g["sea_frac"] = g["sea_frac"].clip(upper=1.0)
    g["level"] = FINE
    return g[["cell_id", "level", "geometry", "sea_frac"]]


def inshore_frac(
    cells: gpd.GeoDataFrame, inshore: gpd.GeoDataFrame, extent: BaseGeometry
) -> pd.Series:
    """Share of each cell's surveyed area inside an inshore fishing polygon; NaN where the survey never reached the
    cell (unknown, never 0). For a fully surveyed cell this is the spec's area / cell area."""
    surveyed = cells.intersection(extent).area
    fishing = (
        cells.intersection(inshore.union_all().intersection(extent)).area
        if len(inshore)
        else 0.0 * surveyed
    )
    out = (fishing / surveyed.where(surveyed > 0)).clip(0, 1)
    return pd.Series(out.to_numpy(float), index=cells.index, name="inshore_frac")


def _res_deg(values: pd.Series) -> float:
    """GFW's grid step in degrees, read off the data: the smallest gap between distinct corner coordinates."""
    gaps = np.diff(np.unique(np.round(values.to_numpy(float), 6)))
    if not len(gaps):
        raise ValueError("cannot read GFW's grid step from a single presence cell")
    return float(gaps.min())


def regrid_presence(presence: pd.DataFrame) -> pd.DataFrame:
    """GFW presence (lon, lat of each grid cell's south-west corner) regridded to 2 km cells, area-weighted (issue 4).
    Each presence cell's hours are split over the 2 km cells it overlaps by overlap area, so no hour is lost."""
    if presence.empty:
        return pd.DataFrame(
            {c: pd.Series(dtype=float if c == "hours" else object) for c in _PRESENCE_COLS}
        )
    step = min(_res_deg(presence["lon"]), _res_deg(presence["lat"]))
    corners = presence[["lon", "lat"]].drop_duplicates().reset_index(drop=True)
    polys = []
    for lon, lat in corners.itertuples(index=False):
        xs, ys = to_utm([lon, lon + step, lon + step, lon], [lat, lat, lat + step, lat + step])
        polys.append(Polygon(zip(xs, ys, strict=True)))  # a degree cell is a quadrilateral in UTM
    src = gpd.GeoDataFrame(corners, geometry=polys, crs=32629)
    src["area"] = src.area
    grid = _grid(tuple(src.total_bounds))
    ov = gpd.overlay(src, grid.reset_index(drop=True), how="intersection", keep_geom_type=True)
    ov["w"] = ov.area / ov["area"]
    ov["w"] = ov["w"] / ov.groupby(["lon", "lat"])["w"].transform("sum")  # exact sum to 1
    out = presence.merge(ov[["lon", "lat", "cell_id", "w"]], on=["lon", "lat"])
    out["hours"] = out["hours"] * out["w"]
    out = out.groupby(["cell_id", "date", "vessel_type", "speed_bin"], as_index=False)[
        "hours"
    ].sum()
    return out[_PRESENCE_COLS]


def _per_cell(cells: gpd.GeoDataFrame, hours: pd.Series) -> pd.Series:
    return hours.reindex(cells.index).fillna(0.0)


def lanes(cells: gpd.GeoDataFrame, presence2km: pd.DataFrame, pct: float = 90) -> pd.Series:
    """Non-fishing hours above the pct-th percentile of non-empty cells."""
    if presence2km.empty:
        return pd.Series(False, index=cells.index, name="lane")
    p = presence2km[presence2km["vessel_type"] != _FISHING]
    h = _per_cell(cells, p.groupby("cell_id")["hours"].sum())
    nonzero = h[h > 0]
    if nonzero.empty:
        return pd.Series(False, index=cells.index, name="lane")
    return (h > np.percentile(nonzero, pct)).rename("lane")


def _bin_low(label: str) -> float:
    """Lower bound of a GFW speed bin label such as '0-2', '2-4' or '8+'."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(label))
    if m is None:
        raise ValueError(f"unreadable speed bin {label!r}")
    return float(m.group(1))


def anchorages(
    cells: gpd.GeoDataFrame,
    presence2km: pd.DataFrame,
    share: float = 0.5,
    top_pct: float = 25,
) -> pd.Series:
    """Share of the cell's hours in GFW's slowest speed bin above `share`, and total hours in the top `top_pct`%
    of non-empty cells."""
    if presence2km.empty:
        return pd.Series(False, index=cells.index, name="anchorage")
    slowest = min(presence2km["speed_bin"].unique(), key=_bin_low)
    total = _per_cell(cells, presence2km.groupby("cell_id")["hours"].sum())
    slow = _per_cell(
        cells, presence2km[presence2km["speed_bin"] == slowest].groupby("cell_id")["hours"].sum()
    )
    nonzero = total[total > 0]
    busy = total >= np.percentile(nonzero, 100 - top_pct)
    frac = slow / total.where(total > 0)
    return ((frac > share) & busy).rename("anchorage")


def port_zones(
    cells: gpd.GeoDataFrame, harbours: gpd.GeoDataFrame, buffer_m: float = 5000
) -> pd.Series:
    """Cells touching a buffer around any port or harbour point."""
    if harbours.empty:
        return pd.Series(False, index=cells.index, name="port_zone")
    zone = harbours.buffer(buffer_m).union_all()
    return pd.Series(cells.intersects(zone).to_numpy(), index=cells.index, name="port_zone")


def exclusion(port_zone: pd.Series, anchorage: pd.Series, grow_cells: int = 1) -> pd.Series:
    """port_zone or anchorage, grown by `grow_cells` cells in every direction (diagonals included).
    Both series are indexed by 2 km cell_id."""
    hit = port_zone | anchorage
    out = hit.copy()
    present = set(hit.index)
    for cid in hit.index[hit.to_numpy(bool)]:
        s, ix, iy = (int(p) for p in str(cid).split("_"))
        for dx in range(-grow_cells, grow_cells + 1):
            for dy in range(-grow_cells, grow_cells + 1):
                n = cell_id(ix + dx, iy + dy, s)
                if n in present:
                    out[n] = True
    return out.rename("exclusion")


def dist_coast(cells: gpd.GeoDataFrame, coastline: BaseGeometry) -> pd.Series:
    """Distance from each cell centre to the coastline, metres (0 where the centre is on land)."""
    return pd.Series(
        cells.centroid.distance(coastline).to_numpy(float), index=cells.index, name="dist_coast_m"
    )


def to_coarse(cells2km: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """10 km cells from the 2 km cells, by the P3 resolved-ambiguity rules: inshore_frac = mean ignoring NaN (NaN if
    all NaN); dist_coast_m, static_frac and sea_frac = means. The spec's lane rule is the share of lane children, but
    the schema keeps lane bool, so a coarse cell is a lane if any child is (raised on #85)."""
    g = cells2km.assign(pcell=[parent(c) for c in cells2km["cell_id"]]).groupby("pcell")
    out = pd.DataFrame(
        {
            "inshore_frac": g["inshore_frac"].mean(),
            "lane": g["lane"].any(),
            "anchorage": g["anchorage"].any(),
            "port_zone": g["port_zone"].any(),
            "exclusion": g["exclusion"].any(),
            "dist_coast_m": g["dist_coast_m"].mean(),
            "static_frac": g["static_frac"].mean(),
            "sea_frac": g["sea_frac"].mean(),
        }
    ).reset_index(names="cell_id")
    x0, y0 = _origin()
    ij = [tuple(int(p) for p in c.split("_")[1:]) for c in out["cell_id"]]
    geom = [
        box(x0 + i * COARSE, y0 + j * COARSE, x0 + (i + 1) * COARSE, y0 + (j + 1) * COARSE)
        for i, j in ij
    ]
    return gpd.GeoDataFrame(out.assign(level=COARSE), geometry=geom, crs=32629)
