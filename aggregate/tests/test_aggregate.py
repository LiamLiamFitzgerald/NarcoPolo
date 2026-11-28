import pandas as pd
import pytest

from aggregate import build_observed, exposure_rows, soft_counts, to_coarse

D1, D2 = pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")


def _both(*days):
    idx = pd.DatetimeIndex(list(days))
    return {"dark_small": idx, "slowdown": idx}


def _cells(ids):
    return pd.DataFrame({"cell_id": ids, "level": 2000, "sea_frac": 0.5})


def test_soft_count_is_sum_of_probabilities_per_utc_date():
    events = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"] * 3,
            "event_type": ["dark_small"] * 3,
            "time_utc": ["2026-10-01T23:30Z", "2026-10-01T01:00Z", "2026-10-02T00:10Z"],
            "p": [0.4, 0.2, 0.9],
        }
    )
    c = soft_counts(events).set_index("date")["count"]
    assert c[D1] == pytest.approx(0.6)
    assert c[D2] == pytest.approx(0.9)


def test_rough_and_missing_passes_add_no_small_boat_exposure():
    exposure = pd.DataFrame(
        {
            "cell_id": ["2000_0_0", "2000_0_0"],
            "time_utc": ["2026-10-01T06:00Z", "2026-10-01T18:00Z"],
            "exposure_small": [0.8, 0.0],  # second pass was rough: P3 writes 0
        }
    )
    rows = exposure_rows(exposure, _cells(["2000_0_0", "2000_1_0"]), _both(D1, D2), D2)
    small = rows[rows.event_type == "dark_small"].set_index(["cell_id", "date"])["exposure"]
    assert small[("2000_0_0", D1)] == pytest.approx(0.8)
    assert small[("2000_0_0", D2)] == 0  # no pass that day
    assert small[("2000_1_0", D1)] == 0  # never covered


def test_slowdown_exposure_is_sea_frac_and_zero_after_gfw_latest_date():
    rows = exposure_rows(
        pd.DataFrame(columns=["cell_id", "time_utc", "exposure_small"]),
        _cells(["2000_0_0"]),
        _both(D1, D2),
        slowdown_last_date=D1,
    )
    slow = rows[rows.event_type == "slowdown"].set_index("date")["exposure"]
    assert slow[D1] == 0.5
    assert slow[D2] == 0


def test_build_observed_keeps_unobserved_rows_as_exposure_zero():
    expo = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"] * 2,
            "date": [D1, D2],
            "event_type": "dark_small",
            "exposure": [1.0, 0.0],
        }
    )
    counts = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"],
            "date": [D1],
            "event_type": "dark_small",
            "count": [0.7],
        }
    )
    f = build_observed(counts, expo).frame.set_index("date")
    assert len(f) == 2
    assert f.loc[D2, "count"] == 0 and f.loc[D2, "exposure"] == 0


def test_event_where_we_never_looked_is_rejected():
    expo = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"],
            "date": [D1],
            "event_type": "dark_small",
            "exposure": [0.0],
        }
    )
    counts = expo.drop(columns="exposure").assign(count=1.0)
    with pytest.raises(ValueError):
        build_observed(counts, expo)


def test_to_coarse_sums_the_25_children():
    ids = [f"2000_{i}_{j}" for i in range(5) for j in range(5)] + ["2000_5_0"]
    expo = pd.DataFrame({"cell_id": ids, "date": D1, "event_type": "slowdown", "exposure": 1.0})
    counts = expo.drop(columns="exposure").assign(count=0.5)
    coarse = to_coarse(build_observed(counts, expo)).frame.set_index("cell_id")
    assert coarse.loc["10000_0_0", "exposure"] == 25
    assert coarse.loc["10000_0_0", "count"] == pytest.approx(12.5)
    assert coarse.loc["10000_1_0", "exposure"] == 1
    assert (coarse["level"] == 10000).all()


def test_build_writes_both_levels_and_both_types_with_no_gaps():
    from aggregate import build

    ids = [f"2000_{i}_0" for i in range(6)]
    events = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"],
            "event_type": ["dark_small"],
            "time_utc": ["2026-10-01T06:10Z"],
            "p": [0.6],
        }
    )
    exposure = pd.DataFrame(
        {
            "cell_id": ["2000_0_0"],
            "time_utc": ["2026-10-01T06:00Z"],
            "exposure_small": [0.9],
        }
    )
    f = build(events, exposure, _cells(ids), _both(D1, D2), D2).frame
    fine, coarse = f[f.level == 2000], f[f.level == 10000]
    assert len(fine) == 6 * 2 * 2  # cells x dates x types, unobserved rows included
    assert set(coarse.cell_id) == {"10000_0_0", "10000_1_0"}
    assert coarse["count"].sum() == pytest.approx(fine["count"].sum()) == pytest.approx(0.6)


def test_each_type_gets_its_own_history_window():
    from aggregate import history_dates

    d = history_dates(
        pd.Timestamp("2026-11-24 13:00"), {"ship_history_days": 730, "radar_history_days": 90}
    )
    assert len(d["slowdown"]) == 730 and len(d["dark_small"]) == 90
    assert d["slowdown"][-1] == d["dark_small"][-1] == pd.Timestamp("2026-11-24")
    assert d["dark_small"][0] == pd.Timestamp("2026-11-24") - pd.Timedelta(days=89)


def _write_cells_layer(cells):
    """A schema-valid cells layer through core.io: P3's columns, a simple square geometry."""
    from shapely.geometry import box

    from core.grid import parent
    from core.io import write_stage

    coarse = pd.DataFrame({"cell_id": sorted(set(cells.cell_id.map(parent))), "level": 10000})
    both = pd.concat([cells, coarse.assign(sea_frac=1.0)], ignore_index=True)
    full = both.assign(
        geometry=pd.Series([box(0, 0, 1, 1)] * len(both)),
        inshore_frac=0.5,
        lane=False,
        anchorage=False,
        port_zone=False,
        exclusion=False,
        dist_coast_m=5000.0,
        static_frac=0.0,
    )
    write_stage("reference/cells", full, "simulated")


def test_stage_reads_inputs_and_writes_a_valid_observed_file(tmp_path, monkeypatch):
    from aggregate import stage
    from core.io import read_stage, write_stage

    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    ids = [f"2000_{i}_0" for i in range(6)]
    _write_cells_layer(_cells(ids))
    t = pd.Timestamp("2026-10-01 06:00", tz="UTC")
    write_stage(
        "coverage/exposure",
        pd.DataFrame(
            {
                "cell_id": ["2000_0_0"],
                "pass_id": ["s1a_1"],
                "time_utc": [t],
                "covered_frac": [1.0],
                "wind_ms": [3.0],
                "hs_m": [0.5],
                "calm": [True],
                "exposure_small": [0.9],
                "post_storm": [False],  # contract #140
            }
        ),
        "simulated",
    )
    write_stage(
        "match/events",
        pd.DataFrame(
            {
                "event_id": ["e1"],
                "event_type": ["dark_small"],
                "time_utc": [t + pd.Timedelta(minutes=5)],
                "x_m": [381000.0],
                "y_m": [5661000.0],
                "cell_id": ["2000_0_0"],
                "p": [0.6],
                "duration_min": [None],
                "ship_key": [None],
                "matched": [False],
            }
        ),
        "simulated",
    )
    cfg = {"ship_history_days": 3, "radar_history_days": 2}
    stage(pd.Timestamp("2026-10-02"), pd.Timestamp("2026-10-02"), cfg, "simulated")
    out = read_stage("aggregate/observed")
    fine = out[out.level == 2000]
    assert len(fine) == 6 * (3 + 2)  # every cell on every day of each type's window
    assert out["count"].sum() == pytest.approx(2 * 0.6)  # the event counted at 2 km and at 10 km
