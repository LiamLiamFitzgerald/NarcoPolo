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
        "cell_id": ["c0"] * 5, "ghost": [False] * 5,
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


def test_ghosts_never_become_dark_small_events():  # #353
    d = _dets().assign(matched=False, ghost=[False, False, True, False, False])
    assert "dark_small-c" not in set(dark_small_events(d)["event_id"])


def _on(c, truth, tol_px=2):
    """det_ids of candidates within tol_px of a truth position."""
    d = np.hypot(c["row"].to_numpy()[:, None] - truth["row"].to_numpy(),
                 c["col"].to_numpy()[:, None] - truth["col"].to_numpy())  # fmt: skip
    return "dark_small-" + c["det_id"][d.min(axis=1) <= tol_px]


def test_simulated_ship_ghost_is_dropped_and_real_boats_survive():
    """#353: a bright ship and its planted azimuth ghost, run through the real detector, then dark_small_events."""
    from detect.pipeline import run_pass
    from detect.scene import to_linear
    from detect.tests._scene import make_scene

    dropped = kept = n_ghosts = n_boats = 0
    for seed in range(5):
        s = make_scene(seed, shape=(1200, 1200), n_boats=5, n_ships=1)
        c = run_pass(
            f"sim{seed}", (to_linear(s.vv), to_linear(s.vh), s.meta), masks=(s.land, s.static)
        )
        ev = set(dark_small_events(c.assign(matched=False, p_boat=0.5))["event_id"])
        g, b = _on(c, s.ghosts), _on(c, s.boats)
        n_ghosts, n_boats = n_ghosts + len(g), n_boats + len(b)
        dropped += int((~g.isin(ev)).sum())
        kept += int(b.isin(ev).sum())
    assert (
        n_ghosts > 0 and dropped / n_ghosts >= 0.8
    )  # spec: ghosts flagged at least 80% of the time
    assert (
        n_boats > 0 and kept == n_boats
    )  # a boat with no bright partner is never dropped as a ghost
