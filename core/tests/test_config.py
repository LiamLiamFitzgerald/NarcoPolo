import hashlib
from datetime import date

import pytest

from core.config import load, snapshot_date


def test_load_is_frozen_and_hashes_the_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("seed: 1\nsplit: {embargo_days: 7}\nrange: [1, 2]\n")
    cfg, h = load(p)
    assert cfg["split"]["embargo_days"] == 7 and cfg["range"] == (1, 2)
    assert h == hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(TypeError):
        cfg["seed"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        cfg["split"]["embargo_days"] = 0  # type: ignore[index]


def test_repo_config_loads_and_origin_nests_cells():
    cfg, _ = load("config.yaml")
    assert cfg["x0"] % 10_000 == 0 and cfg["y0"] % 10_000 == 0
    assert cfg["split"]["embargo_days"] == 7


def test_snapshot_date_is_the_earliest_feed():
    m = {
        "latest": {
            "radar": "2026-11-25",
            "gfw_presence": "2026-11-24",
            "gfw_sar": "2026-11-22",
            "era5": "2026-11-23",
        }
    }
    assert snapshot_date(m) == date(2026, 11, 22)


def test_snapshot_date_needs_every_feed():
    with pytest.raises(KeyError):
        snapshot_date({"latest": {"radar": "2026-11-25"}})
