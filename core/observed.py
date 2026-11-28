"""A count only means something next to its exposure. Rate is defined only where exposure > 0."""

import pandas as pd

COLUMNS = ["cell_id", "level", "date", "event_type", "count", "exposure"]


class Observed:
    """frame[cell_id, level, date, event_type, count, exposure]; unobserved cells (exposure 0) are kept, never counted."""

    def __init__(self, frame: pd.DataFrame):
        missing = [c for c in COLUMNS if c not in frame.columns]
        if missing:
            raise ValueError(f"Observed is missing columns {missing}")
        if bool(frame[["count", "exposure"]].isna().to_numpy().any()):
            raise ValueError("count and exposure may not be missing")
        exposure, count = frame["exposure"].to_numpy(), frame["count"].to_numpy()
        if bool((exposure < 0).any()):
            raise ValueError("exposure < 0")
        if bool(((count > 0) & (exposure == 0)).any()):
            raise ValueError("count > 0 where exposure = 0: an unobserved cell cannot have events")
        self.frame = frame[COLUMNS].reset_index(drop=True)

    def observed_rows(self) -> pd.DataFrame:
        return pd.DataFrame(self.frame[self.frame["exposure"] > 0])

    def rate(self) -> pd.Series:
        o = self.observed_rows()
        return pd.Series(o["count"] / o["exposure"])
