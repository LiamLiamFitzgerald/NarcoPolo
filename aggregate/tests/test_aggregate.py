import pandas as pd
import pytest

from aggregate import build_observed, exposure_rows, soft_counts, to_coarse

D1, D2 = pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")


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
    rows = exposure_rows(
        exposure, _cells(["2000_0_0", "2000_1_0"]), pd.DatetimeIndex([D1, D2]), D2
    )
    small = rows[rows.event_type == "dark_small"].set_index(["cell_id", "date"])[
        "exposure"
    ]
    assert small[("2000_0_0", D1)] == pytest.approx(0.8)
    assert small[("2000_0_0", D2)] == 0  # no pass that day
    assert small[("2000_1_0", D1)] == 0  # never covered


def test_slowdown_exposure_is_sea_frac_and_zero_after_gfw_latest_date():
    rows = exposure_rows(
        pd.DataFrame(columns=["cell_id", "time_utc", "exposure_small"]),
        _cells(["2000_0_0"]),
        pd.DatetimeIndex([D1, D2]),
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
    expo = pd.DataFrame(
        {"cell_id": ids, "date": D1, "event_type": "slowdown", "exposure": 1.0}
    )
    counts = expo.drop(columns="exposure").assign(count=0.5)
    coarse = to_coarse(build_observed(counts, expo)).frame.set_index("cell_id")
    assert coarse.loc["10000_0_0", "exposure"] == 25
    assert coarse.loc["10000_0_0", "count"] == pytest.approx(12.5)
    assert coarse.loc["10000_1_0", "exposure"] == 1
    assert (coarse["level"] == 10000).all()


def test_run_writes_both_levels_and_both_types_with_no_gaps():
    from aggregate import run

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
    f = run(events, exposure, _cells(ids), pd.DatetimeIndex([D1, D2]), D2).frame
    fine, coarse = f[f.level == 2000], f[f.level == 10000]
    assert len(fine) == 6 * 2 * 2  # cells x dates x types, unobserved rows included
    assert set(coarse.cell_id) == {"10000_0_0", "10000_1_0"}
    assert (
        coarse["count"].sum()
        == pytest.approx(fine["count"].sum())
        == pytest.approx(0.6)
    )
