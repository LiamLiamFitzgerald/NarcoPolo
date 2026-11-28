"""#269: the forecast to score against: live (fold 0) where it exists, else the out-of-sample backtest fold."""

import pandas as pd

from core.expected import scoring_rows


def _rows(fold, dates, mu, cell="2000_1_1"):
    return pd.DataFrame(
        {
            "cell_id": cell,
            "date": pd.to_datetime(dates),
            "event_type": "dark_small",
            "mu": mu,
            "fold": pd.array([fold] * len(dates), dtype="Int64"),
        }
    )


def test_live_wins_backtest_fills_earlier_dates_each_key_once():
    e = pd.concat(
        [
            _rows(0, ["2026-11-20", "2026-11-21"], 1.0),  # live
            _rows(1, ["2026-11-21", "2026-11-22"], 9.0),  # backtest overlapping the live window
            _rows(2, ["2026-11-10", "2026-11-11"], 2.0),  # older, out of sample
        ]
    )
    out = scoring_rows(e).set_index("date")["mu"].sort_index()
    assert out.to_dict() == {
        pd.Timestamp("2026-11-10"): 2.0,
        pd.Timestamp("2026-11-11"): 2.0,
        pd.Timestamp("2026-11-20"): 1.0,
        pd.Timestamp("2026-11-21"): 1.0,
        pd.Timestamp("2026-11-22"): 9.0,
    }
    assert not scoring_rows(e).duplicated(["cell_id", "date", "event_type"]).any()


def test_two_backtest_folds_on_one_date_keep_the_most_recent_fit():
    e = pd.concat([_rows(3, ["2026-11-01"], 3.0), _rows(2, ["2026-11-01"], 2.0)])
    assert scoring_rows(e)["mu"].tolist() == [
        2.0
    ]  # fold 1 is the latest cutoff, so lower = most recent


def test_rows_with_unknown_fold_are_not_used_and_no_fold_column_means_all_live():
    e = pd.concat(
        [
            _rows(0, ["2026-11-20"], 1.0),
            _rows(0, ["2026-11-21"], 5.0).assign(fold=pd.array([pd.NA], dtype="Int64")),
        ]
    )
    assert scoring_rows(e)["mu"].tolist() == [1.0]
    assert len(scoring_rows(e.drop(columns="fold"))) == 2
