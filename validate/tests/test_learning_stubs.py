import json

from core.config import load
from core.io import CONFIG_PATH
from validate.train import fit_site_model, model_path


def test_model_file_matches_what_fuse_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    m = fit_site_model(["fixed"], [1, 2])
    on_disk = json.loads(model_path().read_text())
    assert on_disk == m and m["rung"] in (0, 1)  # fuse applies rungs 0 and 1 only
    keys = {
        "rung",
        "features",
        "weights",
        "intercept",
        "config_hash",
        "metrics",
        "seeds",
        "regimes",
    }
    assert keys <= set(m) <= keys | {"params"}
    assert m["config_hash"] == load(CONFIG_PATH)[1]
