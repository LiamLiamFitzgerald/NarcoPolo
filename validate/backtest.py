"""Backtest (docs/specs/P1.md, Validation table): walk-forward skill via forecast.backtest."""

import pandas as pd


def backtest(event_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        columns=["event_type", "model", "mean", "min", "max"]
    )  # TODO(P1): forecast.backtest
