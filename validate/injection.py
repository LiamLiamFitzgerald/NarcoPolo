"""Injection test (docs/specs/P1.md, Validation table): Gaussian spots in linear sigma0, rerun detect.run_pass."""

import pandas as pd


def injection_test(
    pass_ids: list[str], brightness_db: list[float], n_per_pass: int, seed: int
) -> pd.DataFrame:
    return pd.DataFrame(
        columns=["brightness_db", "recall", "false_alarms_per_km2"]
    )  # TODO(P1): detect.run_pass
