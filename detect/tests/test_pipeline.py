import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from detect import _standin
from detect._standin import Split, make_scene
from detect.pboat import fit_pboat
from detect.pipeline import run_all, run_pass
from detect.scene import to_linear


@pytest.fixture(autouse=True)
def grid_origin(monkeypatch):
    monkeypatch.setitem(_standin.CFG, "x0", 490_000.0)
    monkeypatch.setitem(_standin.CFG, "y0", 5_680_000.0)


def _chip(s):
    return to_linear(s.vv), to_linear(s.vh), s.meta


def _hits(cands, truth, tol_px=2):
    if not len(cands) or not len(truth):
        return np.zeros(len(truth), bool)
    d = np.hypot(
        truth["row"].to_numpy()[:, None] - cands["row"].to_numpy(),
        truth["col"].to_numpy()[:, None] - cands["col"].to_numpy(),
    )
    return d.min(axis=1) <= tol_px


def test_run_pass_finds_boats_and_flags_ghosts():
    s = make_scene(7, shape=(1200, 1200), n_boats=20, n_ships=2, land_cols=40)
    c = run_pass("sim7", _chip(s), masks=(s.land, s.static))
    assert _hits(c, s.boats).mean() >= 0.9
    near_ghost = _hits(s.ghosts, c)  # per candidate: sits on a planted ghost
    assert c.loc[near_ghost, "ghost"].all() and near_ghost.any()
    assert c["peak_ratio_vv_db"].notna().all() and c["peak_ratio_vh_db"].notna().all()
    assert str(c["time_utc"].dt.tz) == "UTC" and c["det_id"].is_unique
    assert (c["x_m"] > 500_000 + 40 * 10 + 300).all()  # nothing on land or in the 300 m buffer


def test_injection_recall_and_false_alarms_per_brightness():
    """The report for P1: recall and false candidates per injected brightness (8 scenes x 20 boats)."""
    report = {}
    for ex in (4.0, 6.0, 8.0, 12.0):
        rec, false = [], 0
        for seed in range(8):
            s = make_scene(100 + seed, shape=(500, 500), n_boats=20, boat_excess_db=ex)
            c = run_pass("inj", _chip(s), masks=(s.land, s.static))
            rec.append(_hits(c, s.boats).mean())
            false += int((~_hits(s.boats, c)).sum())
        report[ex] = (float(np.mean(rec)), false)
    print("injection report (excess dB: recall, false candidates over 8 passes):", report)
    recalls = [r for r, _ in report.values()]
    assert recalls == sorted(recalls) and recalls[-1] >= 0.95
    assert all(f <= 4 for _, f in report.values())


def test_run_all_writes_schema_valid_detections_and_drops_rough_cells(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    s = make_scene(9, shape=(500, 500), n_boats=20, land_cols=40, pass_id="p9")
    tr = from_origin(s.meta["x_left"], s.meta["y_top"], 10, 10)
    for d in ("raw/s1", "reference", "coverage"):
        (tmp_path / d).mkdir(parents=True)

    def tif(path, bands, dtype):
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=500,
            width=500,
            count=len(bands),
            dtype=dtype,
            transform=tr,
        ) as f:
            f.write(np.stack(bands))

    tif(tmp_path / "raw/s1/p9.tif", [s.vv, s.vh], "int16")
    (tmp_path / "raw/s1/p9.json").write_text(
        json.dumps({k: v for k, v in s.meta.items() if k not in ("x_left", "y_top")})
    )
    tif(tmp_path / "reference/land_mask_10m.tif", [s.land], "uint8")
    tif(tmp_path / "reference/static_mask_10m.tif", [s.static], "uint8")

    cands = run_pass("p9", root=tmp_path)
    cells = sorted(cands["cell_id"].unique())
    rough = cells[0]
    exposure = pd.DataFrame(
        {"cell_id": cells, "pass_id": "p9", "calm": [c != rough for c in cells], "wind_ms": 3.0}
    )
    exposure.to_parquet(tmp_path / "coverage/exposure.parquet")

    cut = datetime(2026, 12, 1, tzinfo=UTC)
    rng = np.random.default_rng(0)
    inj = pd.DataFrame({"peak_ratio_vv_db": rng.uniform(5, 20, 400), "peak_ratio_vh_db": rng.uniform(5, 20, 400),
                        "pol_agree": rng.random(400) < 0.5, "n_px": rng.integers(1, 5, 400), "wind_ms": rng.uniform(0, 8, 400),
                        "ghost": rng.random(400) < 0.1, "time_utc": cut - pd.Timedelta(days=1)})  # fmt: skip
    inj["is_boat"] = rng.random(400) < 1 / (1 + np.exp(-(inj["peak_ratio_vv_db"] - 12)))
    model = fit_pboat(inj, Split(cut))

    det = pd.read_parquet(run_all(model, root=tmp_path))
    assert len(det) == (cands["cell_id"] != rough).sum() > 0
    assert list(det.columns) == _standin.DETECTIONS_COLUMNS
    assert det["p_boat"].between(0, 1).all() and det["p_boat"].notna().all()


def test_empty_pass_has_every_column():
    s = make_scene(11, shape=(200, 200))
    c = run_pass("empty", _chip(s), masks=(s.land, s.static))
    assert len(c) == 0
    assert set(_standin.DETECTIONS_COLUMNS) - {"p_boat"} <= set(c.columns)


def test_one_pol_ratio_next_to_mask_is_never_nan():
    from detect.pipeline import _ratio_db_at

    img = np.ones((5, 5)) * 4.0
    img[:, :3] = np.nan
    r = _ratio_db_at(img, np.ones((5, 5)), pd.Series([2.0, 2.0]), pd.Series([1.0, 3.0]))
    assert r[0] == 0.0 and np.isclose(r[1], 10 * np.log10(4))


def test_naive_start_time_is_read_as_utc():
    s = make_scene(7, shape=(300, 300), n_boats=5, time_utc="2026-11-01T06:30:00")
    c = run_pass("naive", _chip(s), masks=(s.land, s.static))
    assert (c["time_utc"] == pd.Timestamp("2026-11-01T06:30:00Z")).all()
