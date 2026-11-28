"""#321 end to end on the simulator (#346: fishing boats, planted illegal fishing in a closed area, dark_medium
stand-ins): detectors.run_cells -> fuse.run -> fuse/fisheries, with in_closed_area from reference/closed_areas."""

import shutil

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from core import io
from core.config import load
from fuse.fisheries import closed_cells
from sim.simulate import simulate


def test_closed_cells_by_cell_centre_and_unknown_without_a_layer():
    cells = gpd.GeoDataFrame(
        {"cell_id": ["in", "out"], "level": [2000, 2000]},
        geometry=[box(0, 0, 2000, 2000), box(4000, 0, 6000, 2000)],
        crs="EPSG:32629",
    )
    areas = gpd.GeoDataFrame(
        {"type": ["closure"]}, geometry=[box(-100, -100, 1500, 1500)], crs="EPSG:32629"
    )
    got = closed_cells(cells, areas).set_index("cell_id")["in_closed_area"]
    assert got.to_dict() == {"in": True, "out": False}
    assert closed_cells(cells, None) is None  # no layer: NA, never "outside"
    assert not closed_cells(cells, areas.iloc[:0])[
        "in_closed_area"
    ].any()  # layer with no areas: all outside


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import detectors
    import fuse

    tmp = tmp_path_factory.mktemp("p6fish")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    try:
        simulate(load(cfg)[0], 20261127)
        detectors.run_cells()
        fuse.run()
        names = ("fuse/fisheries", "fuse/sites", "fuse/cells", "aggregate/observed", "forecast/expected",
                 "reference/cells", "reference/travel_hours", "match/events")  # fmt: skip
        out = {n: io.read_stage(n) for n in names}
        out["truth"] = pd.read_parquet(io.truth_path())
        out["T"] = io.read_snapshot()["T"]
    finally:
        mp.undo()
    return out


def test_fisheries_candidates_are_the_planted_illegal_fishing_inside_the_closure(world):
    f, truth = world["fuse/fisheries"], world["truth"]
    ill = truth[truth["kind"] == "illegal_fishing"]
    assert len(f) > 0 and set(f["cell_id"]) <= set(ill["cell_id"])
    assert (f["in_closed_area"] == True).all()  # nullable boolean: NA fails too
    weeks = set(
        pd.to_datetime(ill["time_utc"])
        .dt.tz_convert(None)
        .dt.normalize()
        .dt.to_period("W-SUN")
        .dt.start_time
    )
    assert set(pd.to_datetime(f["week"])) <= weeks
    assert (f["lens"] == "fisheries").all() and f["reasons"].map(
        lambda r: "Inside a closed area." in r
    ).all()


def test_fisheries_lens_does_not_take_the_drop_site(world):
    drop = world["truth"].loc[world["truth"]["kind"] == "drop", "cell_id"].iloc[0]
    assert drop not in set(world["fuse/fisheries"]["cell_id"])


def test_ordinary_fishing_does_not_move_the_drop_off_shortlist(world):
    """#321: fishing must not flood the drop-off list. Fishing boats are dark_medium, and the drop-off lens links
    slowdowns to dark_small only, so removing every dark_medium row leaves the scored sites unchanged."""
    from fuse.link import _run

    w = world
    args = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    frames = [w[n] for n in args]
    no_fish = [
        fr[fr["event_type"] != "dark_medium"] if "event_type" in fr.columns else fr for fr in frames
    ]
    cells = w["fuse/cells"]
    a = _run(*frames, cells=cells, T=w["T"])[1]
    b = _run(*no_fish, cells=cells[cells["event_type"] != "dark_medium"], T=w["T"])[1]
    cols = ["site_id", "S", "p_perm", "bh_flag", "p_site"]
    pd.testing.assert_frame_equal(a[cols].reset_index(drop=True), b[cols].reset_index(drop=True))
