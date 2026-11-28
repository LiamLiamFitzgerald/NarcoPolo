import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_python_m_sim_writes_the_stage_files(tmp_path):
    env = {**os.environ, "NARCO_DATA": str(tmp_path)}
    subprocess.run(
        [sys.executable, "-m", "sim"], cwd=ROOT, env=env, check=True, capture_output=True
    )
    assert (tmp_path / "aggregate" / "observed.parquet").exists()
    assert (tmp_path / "sim" / "truth.parquet").exists()


def test_make_all_names_the_first_module_without_run(monkeypatch):
    """Uses stand-in modules so the test holds whichever real modules have run() yet (#96)."""
    import types

    import pytest

    from scripts.run_all import main

    calls = []
    ready = types.ModuleType("fake_ready")
    ready.run = lambda: calls.append("fake_ready")  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "fake_ready", ready)
    monkeypatch.setitem(sys.modules, "fake_missing", types.ModuleType("fake_missing"))
    monkeypatch.setitem(sys.modules, "fake_after", ready)

    with pytest.raises(SystemExit, match="'fake_missing' has no run()"):
        main(["fake_ready", "fake_missing", "fake_after"])
    assert calls == ["fake_ready"]
