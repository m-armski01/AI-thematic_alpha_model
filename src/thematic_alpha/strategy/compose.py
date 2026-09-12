"""Compose target weights (SPEC §1C).

On each signal date, in order:
1. ranker weights;
2. event mask — a blocked name's share is capped at its previous signal date's share (no
   *increase* in weight); freed budget goes pro-rata to unblocked names;
3. normalize to sum ≤ 1;
4. multiply by the macro-gate exposure;
5. position limits (cap, cash floor).

The result sums to ≤ 1 on every signal date; the remainder is cash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.config import SizingConfig
from thematic_alpha.strategy.event_mask import EventMask
from thematic_alpha.strategy.sizing import apply_limits

logger = logging.getLogger("thematic_alpha.strategy.compose")


@dataclass
class ComposeResult:
    target_weights: pd.DataFrame  # signal_date x ticker
    pre_gate_weights: pd.DataFrame  # signal_date x ticker, after mask + normalize
    exposure: pd.Series  # signal_date
    entries_blocked: int  # (date, ticker) increases prevented by the event mask
    masked_ticker_dates: int  # size of the mask over the signal dates
    failed_open: list[str]


def _apply_mask_row(w: pd.Series, prev: pd.Series, blocked: pd.Series) -> tuple[pd.Series, int]:
    increase = blocked & (w > prev)
    n_blocked = int(increase.sum())
    if n_blocked == 0:
        return w, 0
    out = w.copy()
    out[increase] = prev[increase]
    freed = w.sum() - out.sum()
    unblocked = ~blocked & (out > 0)
    if freed > 0 and unblocked.any():
        out[unblocked] += freed * out[unblocked] / out[unblocked].sum()
    return out, n_blocked


def compose_target_weights(
    ranker_weights: pd.DataFrame,
    exposure: pd.Series,
    signal_dates: pd.DatetimeIndex,
    sizing_cfg: SizingConfig,
    event_mask: EventMask | None = None,
) -> ComposeResult:
    tickers = list(ranker_weights.columns)
    signal_dates = signal_dates[signal_dates.isin(ranker_weights.index)]
    rw = ranker_weights.loc[signal_dates].fillna(0.0)
    exp = exposure.reindex(signal_dates).fillna(1.0)
    blocked_all = (
        event_mask.blocked.reindex(index=signal_dates, columns=tickers).fillna(False)
        if event_mask is not None
        else pd.DataFrame(False, index=signal_dates, columns=tickers)
    )

    pre_gate = np.zeros(rw.shape)
    prev = pd.Series(0.0, index=tickers)
    entries_blocked = 0
    for i, d in enumerate(signal_dates):
        w, n = _apply_mask_row(rw.loc[d], prev, blocked_all.loc[d].astype(bool))
        entries_blocked += n
        total = w.sum()
        if total > 1.0:
            w = w / total
        pre_gate[i] = w.to_numpy()
        prev = w
    pre_gate_df = pd.DataFrame(pre_gate, index=signal_dates, columns=tickers)
    gated = pre_gate_df.mul(exp, axis=0)
    targets = apply_limits(gated, sizing_cfg.max_position_weight, sizing_cfg.cash_floor)

    masked = int(blocked_all.to_numpy().sum())
    failed_open = list(event_mask.failed_open) if event_mask is not None else tickers
    logger.info(
        "event mask: %d entries blocked pre-earnings "
        "(%d ticker-dates masked; %d tickers failed open)",
        entries_blocked,
        masked,
        len(failed_open),
    )
    return ComposeResult(
        target_weights=targets,
        pre_gate_weights=pre_gate_df,
        exposure=exp,
        entries_blocked=entries_blocked,
        masked_ticker_dates=masked,
        failed_open=failed_open,
    )
