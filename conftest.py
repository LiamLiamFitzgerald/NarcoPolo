"""No test may touch the real raw/ or data/ folders (#331): point both at a temp folder."""

import os
import shutil
import tempfile

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dirs():
    tmp = tempfile.mkdtemp(prefix="narco-test-")
    saved = {k: os.environ.get(k) for k in ("NARCO_RAW", "NARCO_DATA")}
    os.environ["NARCO_RAW"] = os.path.join(tmp, "raw")
    os.environ["NARCO_DATA"] = os.path.join(tmp, "data")
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(tmp, ignore_errors=True)
