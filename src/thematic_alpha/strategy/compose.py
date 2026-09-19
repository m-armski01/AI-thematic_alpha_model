"""Compose target weights (SPEC §1C, brief v2 decision 4a).

On each signal date, in order:
1. ranker weights;
2. event mask — a blocked name's share is capped at its previous signal date's share (no
   *increase* in weight); freed budget goes pro-rata to unblocked names;
3. normalize to sum ≤ 1  → ``p`` (the pre-gate book);
4. the macro gate → ``q``:
   * ``scale``: ``q = p × exposure``;
   * ``block_increases``: on a risk-off signal date every non-exempt name is capped at its
     previous signal date's *final* target (no increases, no new entries); decreases and exits
     follow the ranker; blocked weight stays in cash (no redistribution, unlike the mask);
5. position limits (cap, cash floor) → ``w``.

The result sums to ≤ 1 on every signal date; the remainder is cash.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.config import SizingConfig
from thematic_alpha.strategy.event_mask import EventMask
from thematic_alpha.strategy.sizing import apply_limits

logger = logging.getLogger("thematic_alpha.strategy.compose")


@dataclass
class ComposeResult:
    target_weights: pd.DataFrame  # w: signal_date x ticker, final (post-cap)
    pre_gate_weights: pd.DataFrame  # p: after ranker + mask + normalize
    post_gate_weights: pd.DataFrame  # q: after the gate, before the position cap
    exposure: pd.Series  # signal_date (1.0 throughout in block mode)
    entries_blocked: int  # (date, ticker) increases prevented by the event mask
    masked_ticker_dates: int  # size of the mask over the signal dates
    failed_open: list[str]
    risk_off: pd.Series | None = None  # signal_date -> bool, block mode only
    gate_blocked: int = 0  # (date, ticker) increases or entries prevented by the gate block


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
    risk_off: pd.Series | None = None,
    exempt: Iterable[str] = (),
) -> ComposeResult:
    """``risk_off`` switches the gate to block mode (``exposure`` is then ignored)."""
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

    gate_blocked = 0
    if risk_off is None:
        gated = pre_gate_df.mul(exp, axis=0)
        targets = apply_limits(gated, sizing_cfg.max_position_weight, sizing_cfg.cash_floor)
        risk_off_s = None
    else:
        exp = pd.Series(1.0, index=signal_dates, name="exposure")
        risk_off_s = risk_off.reindex(signal_dates).fillna(False).astype(bool)
        capped = np.array([t not in set(exempt) for t in tickers])
        post = np.zeros(rw.shape)
        final = np.zeros(rw.shape)
        prev_w = np.zeros(len(tickers))
        for i, d in enumerate(signal_dates):
            q = pre_gate[i].copy()
            if risk_off_s.loc[d]:
                limit = np.where(capped, prev_w, np.inf)
                gate_blocked += int((q > limit).sum())
                q = np.minimum(q, limit)
            post[i] = q
            row = pd.DataFrame([q], index=[d], columns=tickers)
            final[i] = apply_limits(
                row, sizing_cfg.max_position_weight, sizing_cfg.cash_floor
            ).to_numpy()[0]
            prev_w = final[i]
        gated = pd.DataFrame(post, index=signal_dates, columns=tickers)
        targets = pd.DataFrame(final, index=signal_dates, columns=tickers)
        logger.info(
            "macro gate (block_increases): risk-off on %d of %d signal dates; %d increases or "
            "entries blocked (weight left in cash); exempt: %s",
            int(risk_off_s.sum()),
            len(signal_dates),
            gate_blocked,
            sorted(set(exempt)) or "none",
        )

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
        post_gate_weights=gated,
        exposure=exp,
        entries_blocked=entries_blocked,
        masked_ticker_dates=masked,
        failed_open=failed_open,
        risk_off=risk_off_s,
        gate_blocked=gate_blocked,
    )
