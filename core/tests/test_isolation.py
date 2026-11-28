"""#331: no test may write into the checkout's real raw/, data/ or reports/."""

import os
import subprocess
import sys
from pathlib import Path

from core import io

VARS = ("NARCO_RAW", "NARCO_DATA", "NARCO_REPORTS")


def test_test_run_points_every_root_at_a_temp_folder():
    assert io.raw_root() != io.ROOT / "raw"
    assert io.stage_path("aggregate/observed").parent.parent != io.ROOT / "data"
    for var in VARS:
        assert not Path(os.environ[var]).resolve().is_relative_to(io.ROOT)


def test_a_test_that_writes_to_the_default_roots_leaves_sentinel_folders_untouched(tmp_path):
    """A test file that (like the old fixtures) sets nothing and writes to raw_root() and the data root,
    run under pytest with the env pointing at sentinel 'real' folders: the sentinels must stay as they were."""
    sentinels = {var: tmp_path / var for var in VARS}
    for d in sentinels.values():
        d.mkdir()
        (d / "real.txt").write_text("real download")
    probe = tmp_path / "probe" / "test_probe.py"
    probe.parent.mkdir()
    probe.write_text(
        "from core import io\n"
        "def test_write():\n"
        "    for root in (io.raw_root(), io.stage_path('aggregate/observed').parent.parent):\n"
        "        root.mkdir(parents=True, exist_ok=True)\n"
        "        (root / 'real.txt').write_text('overwritten')\n"
    )
    env = {**os.environ, **{v: str(d) for v, d in sentinels.items()}}
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(io.ROOT / "pyproject.toml"),
            "--rootdir",
            str(io.ROOT),
            str(probe),
        ],
        check=False,
        cwd=io.ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    for d in sentinels.values():
        assert [p.name for p in d.iterdir()] == ["real.txt"]
        assert (d / "real.txt").read_text() == "real download"
