import pandas as pd

from detect.run import run_all
from match import dark_small_events, slowdowns_from_presence, write_events


def test_stub_outputs_are_schema_valid(tmp_path):
    det = pd.read_parquet(run_all(out=tmp_path / "detections.parquet"))
    assert "p_boat" in det.columns
    ev = pd.read_parquet(write_events(dark_small_events(det), slowdowns_from_presence(None, None, None),
                                      out=tmp_path / "events.parquet"))  # fmt: skip
    assert "event_type" in ev.columns
