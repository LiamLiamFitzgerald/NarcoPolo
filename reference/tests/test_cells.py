"""reference/cells (#34) against the simulator's planted map: lane rows, the anchorage, the port and inshore grounds.

Until the simulator writes raw/gfw_presence.parquet (#93), the presence here is built in GFW's raw shape (lon, lat of a
0.01 degree cell's south-west corner) from the simulator's planted layers, then run through regrid_presence."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from core import io
from core.config import load
from core.crs import to_wgs84
from core.grid import FINE, _origin
from reference import cells as rc
from sim.simulate import simulate


@pytest.fixture(scope="module")
def truth(tmp_path_factory) -> gpd.GeoDataFrame:
    """The simulator's fine cells, with their planted layers, indexed by cell_id."""
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp_path_factory.mktemp("data")))
    mp.setenv("NARCO_RAW", str(tmp_path_factory.mktemp("raw")))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    fine = io.read_stage("reference/cells").query("level == 2000")
    mp.undo()
    return gpd.GeoDataFrame(fine, crs=32629).set_index("cell_id", drop=False)


def _raw_presence(truth: gpd.GeoDataFrame, days: int = 30) -> pd.DataFrame:
    """GFW-shaped presence: fast transit hours on lane cells, mostly slow hours in the anchorage, some anywhere."""
    rng = np.random.default_rng(1)
    rows = []
    pts = truth.geometry.centroid
    for x, y, lane, anchorage, inshore in zip(
        pts.x, pts.y, truth["lane"], truth["anchorage"], truth["inshore_frac"], strict=True
    ):
        for d in range(days):
            if lane:
                rows.append((x, y, d, "8+", "cargo", 2.0))
            if anchorage:
                rows.append((x, y, d, "0-2", "tanker", 3.0))
                rows.append((x, y, d, "8+", "tanker", 0.5))
            if rng.random() < 0.05:  # a few ships passing elsewhere
                rows.append((x, y, d, "2-4", "cargo", 0.3))
            if inshore > 0.5 and rng.random() < 0.5:  # fishing boats never make a lane
                rows.append((x, y, d, "8+", "fishing", 5.0))
    df = pd.DataFrame(rows, columns=["x", "y", "day", "speed_bin", "vessel_type", "hours"])
    lon, lat = to_wgs84(df["x"].to_numpy(), df["y"].to_numpy())
    return pd.DataFrame(
        {
            "lon": np.round(np.floor(lon / 0.01) * 0.01, 2),
            "lat": np.round(np.floor(lat / 0.01) * 0.01, 2),
            "date": pd.Timestamp("2026-08-01") + pd.to_timedelta(df["day"], unit="D"),
            "speed_bin": df["speed_bin"],
            "vessel_type": df["vessel_type"],
            "hours": df["hours"],
        }
    )


def test_regrid_keeps_every_hour(truth):
    raw = _raw_presence(truth)
    out = rc.regrid_presence(raw)
    assert list(out.columns) == ["cell_id", "date", "vessel_type", "speed_bin", "hours"]
    # area weights of each presence cell sum to 1 over the 2 km cells it overlaps
    assert out["hours"].sum() == pytest.approx(raw["hours"].sum(), rel=1e-6)
    assert out["cell_id"].str.startswith("2000_").all()


def test_planted_lane_and_anchorage_recovered(truth):
    p2 = rc.regrid_presence(_raw_presence(truth))
    lane = rc.lanes(truth, p2)
    anch = rc.anchorages(truth, p2)
    # The lane rule flags only the top (100 - 90)% of non-empty cells, while the simulator plants lanes on 15% of
    # all cells, so not every planted lane cell can be found (reported on #86). What must hold: the share flagged
    # is the percentile's, and every flagged cell is a planted lane cell or one a 0.01 degree cell spills into.
    ships = p2[p2["vessel_type"] != "fishing"]
    nonempty = (ships.groupby("cell_id")["hours"].sum() > 0).sum()
    assert 0 < lane.sum() <= 0.1 * nonempty  # "above" the percentile: ties at it are not lanes
    iy = truth["cell_id"].str.split("_").str[2].astype(int)
    lane_rows = set(iy[truth["lane"]])
    near = iy.isin({r + d for r in lane_rows for d in (-1, 0, 1)})
    # the busy anchorage also passes the lane rule (its ships are non-fishing); exclusion covers it anyway
    assert (near | truth["anchorage"])[lane].all()
    assert truth["lane"][lane & ~truth["anchorage"]].mean() >= 0.8
    assert anch[truth["anchorage"]].all()
    assert not anch[~truth["anchorage"] & ~truth["lane"]].any()
    assert not lane[truth["inshore_frac"] == 1].any()  # fishing hours never count towards a lane


def test_empty_presence_flags_nothing(truth):
    p2 = rc.regrid_presence(pd.DataFrame())
    assert not rc.lanes(truth, p2).any() and not rc.anchorages(truth, p2).any()


def test_exclusion_grows_by_one_cell():
    ids = [f"2000_{i}_{j}" for i in range(5) for j in range(5)]
    port = pd.Series(False, index=ids)
    anch = pd.Series(False, index=ids)
    port["2000_2_2"] = True
    ex = rc.exclusion(port, anch)
    assert ex.sum() == 9  # the cell and its 8 neighbours
    assert ex["2000_1_1"] and ex["2000_3_3"] and not ex["2000_0_0"]


def test_build_cells_keeps_cells_at_least_one_fifth_sea():
    x0, y0 = _origin()
    region = box(x0, y0, x0 + 3 * FINE, y0 + FINE)
    # land covers all of cell 0, 90% of cell 1 and none of cell 2
    land = box(x0, y0, x0 + FINE, y0 + FINE).union(box(x0 + FINE, y0, x0 + 1.9 * FINE, y0 + FINE))
    out = rc.build_cells(region, land)
    assert list(out.index) == ["2000_2_0"]  # cell 1 is only 10% sea
    land = box(x0, y0, x0 + 1.7 * FINE, y0 + FINE)
    out = rc.build_cells(region, land)
    assert out.loc["2000_1_0", "sea_frac"] == pytest.approx(0.3)


def test_inshore_is_nan_outside_the_survey_not_zero():
    x0, y0 = _origin()
    region = box(x0, y0, x0 + 3 * FINE, y0 + FINE)
    cells = rc.build_cells(region, Point(0, 0).buffer(1))
    inshore = gpd.GeoDataFrame(geometry=[box(x0, y0, x0 + 0.5 * FINE, y0 + FINE)], crs=32629)
    extent = box(x0, y0, x0 + 2 * FINE, y0 + FINE)  # the survey did not reach cell 2
    f = rc.inshore_frac(cells, inshore, extent)
    assert f["2000_0_0"] == pytest.approx(0.5)
    assert f["2000_1_0"] == 0.0  # surveyed, no fishing: a real zero
    assert np.isnan(f["2000_2_0"])  # not surveyed: unknown


def test_to_coarse_rules():
    ids = [f"2000_{i}_0" for i in range(5)]
    x0, y0 = _origin()
    fine = gpd.GeoDataFrame(
        {
            "cell_id": ids,
            "level": 2000,
            "inshore_frac": [np.nan, 0.2, 0.4, np.nan, np.nan],
            "lane": [True, False, False, False, False],
            "anchorage": False,
            "port_zone": False,
            "exclusion": False,
            "dist_coast_m": [1000.0, 2000, 3000, 4000, 5000],
            "static_frac": 0.0,
            "sea_frac": 1.0,
        },
        geometry=[box(x0 + i * FINE, y0, x0 + (i + 1) * FINE, y0 + FINE) for i in range(5)],
        crs=32629,
    )
    c = rc.to_coarse(fine).iloc[0]
    assert c["cell_id"] == "10000_0_0"
    assert c["inshore_frac"] == pytest.approx(0.3)  # NaN children ignored
    assert c["dist_coast_m"] == pytest.approx(3000)
    assert c["lane"]  # schema keeps lane bool: any lane child
