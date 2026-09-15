"""Benchmarks (SPEC §1D), all run through the same engine with identical cost treatment:

1. ``sp500``           — ``benchmarks[0]`` buy-and-hold (SPY, dividend-adjusted; one purchase,
                         then untouched). Layer 1 used ^GSPC, a price-return index.
2. ``equal_weight_bh`` — equal-weight buy-and-hold of the universe. The critical benchmark.
                         Re-equalized only on signal dates where the eligible set changes
                         (a new listing crossing ``min_history_days``); otherwise untouched.
3. ``naive_momentum``  — equal-weight top-N by ``mom_63`` every signal date, no gate, no mask.
"""

from __future__ import annotations

import pandas as pd

from thematic_alpha.strategy.ranker import naive_momentum


def single_asset_targets(ticker: str, first_signal: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame({ticker: [1.0]}, index=pd.DatetimeIndex([first_signal]))


def buy_and_hold_targets(eligible: pd.DataFrame, signal_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Equal-weight rows only on the first signal date and whenever the eligible set changes."""
    elig = eligible.reindex(signal_dates).fillna(False).astype(bool)
    rows = {}
    prev: frozenset[str] = frozenset()
    for d in signal_dates:
        current = frozenset(elig.columns[elig.loc[d].to_numpy()])
        if current and current != prev:
            rows[d] = {t: (1.0 / len(current) if t in current else 0.0) for t in elig.columns}
            prev = current
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=elig.columns)


def naive_momentum_targets(
    wide: dict[str, pd.DataFrame],
    eligible: pd.DataFrame,
    signal_dates: pd.DatetimeIndex,
    top_n: int,
) -> pd.DataFrame:
    return naive_momentum(wide, eligible, top_n).reindex(signal_dates).fillna(0.0)
