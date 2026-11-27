import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_python_m_sim_writes_the_stage_files(tmp_path):
    env = {**os.environ, "NARCO_DATA": str(tmp_path)}
    subprocess.run(
        [sys.executable, "-m", "sim"], cwd=ROOT, env=env, check=True, capture_output=True
    )
    assert (tmp_path / "aggregate" / "observed.parquet").exists()
    assert (tmp_path / "sim" / "truth.parquet").exists()


def test_make_all_names_the_first_module_without_run(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "scripts.run_all"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "has no run()" in (r.stderr + r.stdout)
