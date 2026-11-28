"""#266: the visible-pickups recovery runs the season in a scratch root with only sim.pickup_length_m changed."""

import os

import scripts.run_all
import sim.simulate
from core import io
from core.config import load
from validate import checks


def test_visible_recovery_overrides_only_pickup_length_and_restores_state(monkeypatch):
    seen = {}
    before = (io.CONFIG_PATH, os.environ.get("NARCO_DATA"), os.environ.get("NARCO_RAW"))
    real = load(io.CONFIG_PATH)[0]

    def fake_simulate(cfg, seed):
        seen["cfg"], seen["seed"], seen["data"] = cfg, seed, os.environ["NARCO_DATA"]

    monkeypatch.setattr(sim.simulate, "simulate", fake_simulate)
    monkeypatch.setattr(scripts.run_all, "main", lambda: seen.setdefault("ran", True))
    monkeypatch.setattr(
        checks,
        "simulator_recovery",
        lambda: {"planted_site_rank": 3, "planted_site_in_top_k": True},
    )
    out = checks.visible_recovery()
    want = list(real["validate"]["visible_pickup_length_m"])
    assert out["pickup_length_m"] == want and out["planted_site_rank"] == 3 and seen["ran"]
    assert list(seen["cfg"]["sim"]["pickup_length_m"]) == want
    assert {k: v for k, v in seen["cfg"]["sim"].items() if k != "pickup_length_m"} == {
        k: v for k, v in real["sim"].items() if k != "pickup_length_m"
    }
    assert (
        seen["seed"] == real["seed"] and seen["data"] != before[1]
    )  # a scratch root, never the user's data/
    assert (io.CONFIG_PATH, os.environ.get("NARCO_DATA"), os.environ.get("NARCO_RAW")) == before
