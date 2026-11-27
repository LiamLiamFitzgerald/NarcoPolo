import numpy as np
import pandas as pd
import pytest

from match import _standin, slowdowns_from_presence, slowdowns_from_tracks

CELLS = pd.DataFrame({"cell_id": ["0_0", "1_0", "2_0"], "exclusion": [False, True, False],
                      "x_m": [1000.0, 3000.0, 5000.0], "y_m": [1000.0] * 3})  # fmt: skip


def _era5(hs_by_cell, date="2026-11-03"):
    return pd.DataFrame([{"cell_id": c, "date": date, "hs_m": h} for c, hs in hs_by_cell.items() for h in hs])


@pytest.fixture(autouse=True)
def grid(monkeypatch):
    monkeypatch.setitem(_standin.CFG, "x0", 0.0)
    monkeypatch.setitem(_standin.CFG, "y0", 0.0)
    monkeypatch.setenv(_standin.CFG["ship_key_salt_env"], "test-salt")


def test_presence_slowdowns_rules():
    pres = pd.DataFrame({
        "cell_id": ["0_0", "0_0", "1_0", "2_0", "0_0", "2_0"], "date": ["2026-11-03"] * 6,
        "vessel_type": ["cargo", "tanker", "cargo", "cargo", "fishing", "cargo"],
        "speed_max_kn": [2, 2, 2, 2, 2, 6], "hours": [0.5, 0.25, 3.0, 1.0, 9.0, 4.0],
    })  # fmt: skip
    era5 = _era5({"0_0": [1.0, 2.0], "1_0": [1.0], "2_0": [3.0, 4.5]})  # 2_0 is stormy that day
    ev = slowdowns_from_presence(pres, CELLS, era5)
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["cell_id"] == "0_0" and e["duration_min"] == 45 and e["p"] == 1.0 and e["ship_key"] is None
    assert e["time_utc"] == pd.Timestamp("2026-11-03T12:00:00Z")
    assert (e["x_m"], e["y_m"]) == (1000.0, 1000.0)


def test_no_slowdown_events_inside_exclusion():
    rng = np.random.default_rng(0)
    n = 500
    pres = pd.DataFrame({"cell_id": rng.choice(CELLS["cell_id"], n), "date": "2026-11-03", "vessel_type": "cargo",
                         "speed_max_kn": 2, "hours": rng.uniform(0.1, 3, n)})  # fmt: skip
    ev = slowdowns_from_presence(pres, CELLS, _era5({c: [1.0] for c in CELLS["cell_id"]}))
    assert len(ev) == 2 and "1_0" not in set(ev["cell_id"])


def _track(slow_min=40, ping_min=5, x0=1000.0, ship_type=70, ship_id="S1"):
    t0 = pd.Timestamp("2026-11-03T00:00:00Z")
    rows, t, x = [], t0, x0
    for phase_kn, minutes in ((13, 120), (2, slow_min), (13, 60)):
        for _ in range(minutes // ping_min):
            rows.append(
                {"ship_id": ship_id, "time_utc": t, "x_m": x, "y_m": 1000.0, "sog_kn": phase_kn, "ship_type": ship_type}
            )
            t += pd.Timedelta(minutes=ping_min)
            x += phase_kn * 0.514444 * ping_min * 60 / 50  # stays inside the 2 km cell
    return pd.DataFrame(rows)


def test_track_slowdown_found_with_duration():
    ev = slowdowns_from_tracks(_track(), cells=CELLS, era5=_era5({"0_0": [1.0]}))
    assert len(ev) == 1
    e = ev.iloc[0]
    # a 40 min stop with 5 min pings: the 10 min rolling median turns slow one ping late -> 30 min
    assert e["duration_min"] == 30 and e["p"] == 1.0
    assert e["time_utc"] >= pd.Timestamp("2026-11-03T02:00:00Z")


def test_track_rules_skip_short_sparse_excluded_and_non_cargo():
    era5 = _era5({"0_0": [1.0], "1_0": [1.0]})
    assert slowdowns_from_tracks(_track(slow_min=15), cells=CELLS, era5=era5).empty  # too short
    assert slowdowns_from_tracks(_track(ping_min=25), cells=CELLS, era5=era5).empty  # too few pings
    assert slowdowns_from_tracks(_track(x0=3000.0), cells=CELLS, era5=era5).empty  # in exclusion
    assert slowdowns_from_tracks(_track(ship_type=30), cells=CELLS, era5=era5).empty  # fishing
    assert slowdowns_from_tracks(_track(), cells=CELLS, era5=_era5({"0_0": [4.2]})).empty  # storm


def test_gap_in_slow_segment_is_never_bridged():
    tr = _track(slow_min=60)
    slow = tr.index[tr["sog_kn"] == 2]
    tr = tr.drop(slow[2:9])  # a 40-minute hole in the middle of the stop
    ev = slowdowns_from_tracks(tr, cells=CELLS, era5=_era5({"0_0": [1.0]}))
    assert (ev["duration_min"] < 40).all()
