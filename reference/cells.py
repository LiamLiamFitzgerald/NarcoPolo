"""2 km cells and their static layers (docs/specs/P3.md). Stubs (#22): right names, types and columns, neutral values;
the real layers come in #34. Thresholds wait for P3's config keys."""

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from core.grid import COARSE, FINE, _origin, cell_id, parent


def build_cells(region: BaseGeometry, coastline: BaseGeometry) -> gpd.GeoDataFrame:
    """2 km cells of `region` (UTM polygon) with sea_frac = sea area / cell area. `coastline` is the land polygon."""
    x0, y0 = _origin()
    xmin, ymin, xmax, ymax = region.bounds
    rows = []
    for ix in range(int((xmin - x0) // FINE), int(np.ceil((xmax - x0) / FINE))):
        for iy in range(int((ymin - y0) // FINE), int(np.ceil((ymax - y0) / FINE))):
            cell = box(x0 + ix * FINE, y0 + iy * FINE, x0 + (ix + 1) * FINE, y0 + (iy + 1) * FINE)
            sea = cell.intersection(region).difference(coastline).area / cell.area
            # stub: keeps only all-sea cells; #34 keeps sea_frac >= the config minimum (0.2 in the spec)
            if sea >= 1 - 1e-9:
                rows.append((cell_id(ix, iy, FINE), FINE, cell, 1.0))
    return gpd.GeoDataFrame(
        rows, columns=["cell_id", "level", "geometry", "sea_frac"], geometry="geometry", crs=32629
    )


def inshore_frac(
    cells: gpd.GeoDataFrame, inshore: gpd.GeoDataFrame, extent: BaseGeometry
) -> pd.Series:
    """Share of each cell inside an inshore fishing polygon; NaN outside the survey extent, never 0."""
    return pd.Series(np.nan, index=cells.index, dtype=float)  # stub: unknown everywhere


def regrid_presence(presence: pd.DataFrame) -> pd.DataFrame:
    """GFW presence regridded to 2 km cells, area-weighted (issue 4)."""
    return pd.DataFrame(
        {
            "cell_id": pd.Series(dtype=str),
            "date": pd.Series(dtype="datetime64[ns]"),
            "vessel_type": pd.Series(dtype=str),
            "speed_bin": pd.Series(dtype=str),
            "hours": pd.Series(dtype=float),
        }
    )  # stub: no presence


def lanes(cells: gpd.GeoDataFrame, presence2km: pd.DataFrame) -> pd.Series:
    """Non-fishing hours above the lane percentile of non-empty cells."""
    return pd.Series(False, index=cells.index)  # stub


def anchorages(cells: gpd.GeoDataFrame, presence2km: pd.DataFrame) -> pd.Series:
    """Slowest-bin share above the anchorage share and total hours in the top quarter."""
    return pd.Series(False, index=cells.index)  # stub


def port_zones(
    cells: gpd.GeoDataFrame, harbours: gpd.GeoDataFrame, buffer_m: float = 5000
) -> pd.Series:
    """Cells touching a buffer around any port or harbour point."""
    if harbours.empty:
        return pd.Series(False, index=cells.index)
    return pd.Series(cells.intersects(harbours.buffer(buffer_m).union_all()), index=cells.index)


def exclusion(port_zone: pd.Series, anchorage: pd.Series) -> pd.Series:
    """port_zone or anchorage, grown by one cell."""
    return port_zone | anchorage  # stub: #34 grows it by one cell


def dist_coast(cells: gpd.GeoDataFrame, coastline: BaseGeometry) -> pd.Series:
    """Distance from each cell centre to the coastline, metres."""
    return pd.Series(cells.centroid.distance(coastline), index=cells.index, dtype=float)


def to_coarse(cells2km: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """10 km cells from complete 2 km cells, by the P3 resolved-ambiguity rules."""
    g = cells2km.assign(pcell=[parent(c) for c in cells2km["cell_id"]]).groupby("pcell")
    out = pd.DataFrame(
        {
            "inshore_frac": g["inshore_frac"].mean(),  # skips NaN; NaN if every child is NaN
            "lane": g["lane"].mean() > 0,  # stub: spec says share of lane children; schema is bool
            "anchorage": g["anchorage"].any(),
            "port_zone": g["port_zone"].any(),
            "exclusion": g["exclusion"].any(),
            "dist_coast_m": g["dist_coast_m"].mean(),
            "static_frac": g["static_frac"].mean(),
            "sea_frac": g["sea_frac"].mean(),  # mean of kept children, so always >= their minimum
        }
    ).reset_index(names="cell_id")
    x0, y0 = _origin()
    ij = [tuple(int(p) for p in c.split("_")[1:]) for c in out["cell_id"]]
    geom = [
        box(x0 + i * COARSE, y0 + j * COARSE, x0 + (i + 1) * COARSE, y0 + (j + 1) * COARSE)
        for i, j in ij
    ]
    return gpd.GeoDataFrame(out.assign(level=COARSE), geometry=geom, crs=32629)
