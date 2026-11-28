"""Pytest plugin, loaded for every run via pyproject addopts (#331).

Points NARCO_RAW, NARCO_DATA and NARCO_REPORTS at a fresh temp folder before any test is collected, so no test
(or subprocess it starts) can write into the checkout's real raw/, data/ or reports/. Tests that set their own
folders with monkeypatch still win; when they undo, they fall back to the temp folder, not the repo.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

VARS = {"NARCO_RAW": "raw", "NARCO_DATA": "data", "NARCO_REPORTS": "reports"}
_saved: dict[str, str | None] = {}
_tmp: list[Path] = []


def pytest_configure(config: pytest.Config) -> None:
    root = Path(tempfile.mkdtemp(prefix="narco-test-"))
    _tmp.append(root)
    for var, sub in VARS.items():
        _saved[var] = os.environ.get(var)
        os.environ[var] = str(
            root / sub
        )  # overrides a value set in the shell too: tests never see real data


def pytest_unconfigure(config: pytest.Config) -> None:
    for var, old in _saved.items():
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old
    for root in _tmp:
        shutil.rmtree(root, ignore_errors=True)
