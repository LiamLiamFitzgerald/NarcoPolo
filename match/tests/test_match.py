import numpy as np
import pandas as pd

from match import dark_small_events, match

T = pd.Timestamp("2026-11-01T06:30:00Z")


def _dets():
    return pd.DataFrame({
        "det_id": ["a", "b", "c", "d", "e"], "pass_id": ["p1"] * 4 + ["p2"],
        "time_utc": [T] * 4 + [T + pd.Timedelta(days=6)],
        "x_m": [0.0, 300.0, 5000.0, 10_000.0, 0.0], "y_m": [0.0] * 5,
        "size_class": ["large", "large", "small", "medium", "small"], "p_boat": [0.9, 0.8, 0.6, 0.3, 0.5],
        "cell_id": ["c0"] * 5,
    })  # fmt: skip


def test_match_is_one_to_one_within_gate_and_same_pass():
    gfw = pd.DataFrame({
        "x_m": [100.0, 5600.0, 9990.0, 0.0, 0.0], "y_m": [0.0] * 5,
        "time_utc": [T, T, T, T, T], "matched": [True, True, False, True, True],
    })  # fmt: skip
    m = match(_dets(), gfw)
    # a, b pair one-to-one with the GFW rows at 0 m and 100 m; c's nearest is 600 m away (beyond the gate);
    # d's GFW row has matched = False; e is in a pass 6 days later with no GFW rows.
    assert list(m) == [True, True, False, False, False]


def test_simulated_matching_recovers_ais_ships():
    rng = np.random.default_rng(0)
    n = 200
    ships = pd.DataFrame({"x_m": rng.uniform(0, 1e5, n), "y_m": rng.uniform(0, 1e5, n)})
    dets = ships.assign(x_m=ships["x_m"] + rng.normal(0, 100, n), y_m=ships["y_m"] + rng.normal(0, 100, n),
                        pass_id="p", time_utc=T)  # fmt: skip
    gfw = ships.iloc[:150].assign(time_utc=T + pd.Timedelta(minutes=1), matched=True)
    m = match(dets, gfw)
    assert m[:150].mean() > 0.98 and not m[150:].any()


def test_dark_small_events_keep_unmatched_small_and_medium():
    d = _dets().assign(matched=[True, False, False, False, True])
    ev = dark_small_events(d)
    assert list(ev["event_id"]) == ["dark_small-c", "dark_small-d"]
    assert (
        list(ev["p"]) == [0.6, 0.3]
        and (ev["event_type"] == "dark_small").all()
        and not ev["matched"].any()
    )
