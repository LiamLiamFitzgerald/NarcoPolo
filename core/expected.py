"""The forecast to score observed counts against (#269).

forecast/expected holds the live forecast (fold 0, the evaluation window) and weekly out-of-sample backtest folds
(fold k >= 1, each fitted before its own week). The lag link needs expectations over the whole radar history,
which is longer than the live window, so for a date with no live row the backtest fold covering it is used:
every expectation still comes from a fit that never saw that date (principle 6). Rows with an unknown fold are
not used. Unobserved stays unobserved: this only picks forecast rows, it never fills counts.
"""

import pandas as pd

KEY = ["cell_id", "date", "event_type"]


def scoring_rows(expected: pd.DataFrame) -> pd.DataFrame:
    """One forecast row per (cell_id, date, event_type): fold 0 if present, else the lowest backtest fold (fold 1
    has the latest cutoff, so the lowest fold is the most recent fit). No `fold` column: every row is live."""
    if "fold" not in expected:
        return expected
    e = expected[expected["fold"].notna()]
    e = e.assign(_f=e["fold"].astype(int)).sort_values("_f", kind="stable")
    return e.drop_duplicates(KEY, keep="first").drop(columns="_f").reset_index(drop=True)
