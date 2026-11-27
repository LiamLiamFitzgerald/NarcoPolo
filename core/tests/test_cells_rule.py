import shutil

import pytest

from core import io
from core.tests.test_schemas import frame


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)


def test_cells_layer_must_exist_first(data):
    with pytest.raises(FileNotFoundError, match="reference/cells"):
        io.write_stage("aggregate/observed", frame("aggregate/observed"), "simulated")


def test_unknown_cell_id_rejected_on_write_for_every_file_with_a_cell_id(data):
    io.write_stage("reference/cells", frame("reference/cells"), "simulated")
    for name in io.SCHEMAS:
        if name == "reference/cells" or "cell_id" not in io.SCHEMAS[name].columns:
            continue
        with pytest.raises(ValueError, match="not in reference/cells"):
            io.write_stage(name, frame(name, cell_id="2000_99_99"), "simulated")
        io.write_stage(name, frame(name), "simulated")  # the known cell is fine


def test_unknown_cell_id_rejected_on_read(data):
    io.write_stage("reference/cells", frame("reference/cells"), "simulated")
    io.write_stage("aggregate/observed", frame("aggregate/observed"), "simulated")
    io.write_stage(
        "reference/cells", frame("reference/cells", cell_id="2000_5_5"), "simulated"
    )  # cells layer changed
    with pytest.raises(ValueError, match="not in reference/cells"):
        io.read_stage("aggregate/observed")
