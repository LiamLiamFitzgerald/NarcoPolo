"""Per-pass detection and the full run to detect/detections.parquet."""

from pathlib import Path

import pandas as pd

from detect._standin import DETECTIONS_COLUMNS, check_detections


def run_pass(pass_id, img=None) -> pd.DataFrame:  # stub, issue #7
    return pd.DataFrame(columns=DETECTIONS_COLUMNS)


def run_all(out: Path = Path("detect/detections.parquet")) -> Path:  # stub, issue #7
    df = run_pass("stub").astype({"p_boat": float, "n_px": int, "pol_agree": bool, "ghost": bool})
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    check_detections(df).to_parquet(out)
    return out
