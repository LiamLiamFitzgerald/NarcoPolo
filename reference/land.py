"""Land polygons from coastline lines (#105, contract #133): the one land every P3 layer and P7's basemap share.

OSM delivers the coastline as lines with land on the left of the drawing direction (the OSM `natural=coastline`
convention; the simulator draws its line the same way). The lines are clipped to the region and the region is cut
into faces along them. Each coastline segment then votes: a probe point just to its left marks land, one just to its
right marks sea, and a face is land when it gets more land votes than sea votes. Closed rings drawn counter-clockwise
(islands) are land inside. A face no coastline touches gets no votes and stays sea: no land is invented.
"""

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

_PROBE_M = (
    1.0  # probe offset from a segment's midpoint: a geometric tolerance, far below the 10 m grid
)
# A coastline that ends on the region's edge must touch it exactly, or the region is never cut. After a lon/lat
# round trip an end can sit ~1e-10 m inside the edge, so an end this close is pushed out past the edge and the
# line clipped again (a geometric tolerance, like _PROBE_M; a real gap in the coastline is far wider).
_SNAP_M = 1.0


def _probes(lines: BaseGeometry) -> tuple[np.ndarray, np.ndarray]:
    """Points just left and just right of every segment's midpoint."""
    left, right = [], []
    for part in getattr(lines, "geoms", [lines]):
        xy = np.asarray(part.coords)[:, :2]
        a, b = xy[:-1], xy[1:]
        d = b - a
        length = np.hypot(d[:, 0], d[:, 1])
        ok = length > 0
        normal = np.c_[-d[ok, 1], d[ok, 0]] / length[ok, None]  # 90 degrees anticlockwise = left
        eps = np.minimum(_PROBE_M, length[ok] / 4)[:, None]
        mid = (a[ok] + b[ok]) / 2
        left.append(mid + eps * normal)
        right.append(mid - eps * normal)
    return np.vstack(left), np.vstack(right)


def _reach_edge(lines: BaseGeometry, region: BaseGeometry) -> BaseGeometry:
    """Extend every line end within _SNAP_M of the region's edge by 2 x _SNAP_M along the line, then clip."""
    edge = region.boundary
    out = []
    for part in getattr(lines, "geoms", [lines]):
        xy = np.asarray(part.coords)[:, :2].copy()
        if len(xy) >= 2 and not part.is_closed:
            for end, nxt in ((0, 1), (-1, -2)):
                p = shapely.Point(xy[end])
                if 0 < p.distance(edge) <= _SNAP_M:
                    d = xy[end] - xy[nxt]
                    xy[end] = xy[end] + 2 * _SNAP_M * d / np.hypot(*d)
        out.append(shapely.LineString(xy).intersection(region))
    return unary_union(out)


def land(coastline: gpd.GeoDataFrame, region: BaseGeometry) -> gpd.GeoDataFrame:
    """Land inside `region` (UTM polygon) as one (multi)polygon row: columns id, geometry, EPSG:32629."""
    lines = shapely.line_merge(unary_union(list(coastline.to_crs(32629).geometry))).intersection(
        region
    )
    lines = unary_union(
        [g for g in getattr(lines, "geoms", [lines]) if g.geom_type in ("LineString", "LinearRing")]
    )
    if lines.is_empty:
        return gpd.GeoDataFrame({"id": [0]}, geometry=[shapely.Polygon()], crs=32629)
    lines = _reach_edge(lines, region)
    faces = np.array(list(polygonize(unary_union([lines, region.boundary]))), dtype=object)
    left, right = _probes(lines)
    tree = shapely.STRtree(faces)

    def votes(pts: np.ndarray) -> np.ndarray:
        hit = tree.query(shapely.points(pts), predicate="within")[1]
        return np.bincount(hit, minlength=len(faces))

    keep = faces[votes(left) > votes(right)]
    return gpd.GeoDataFrame({"id": [0]}, geometry=[unary_union(list(keep))], crs=32629)
