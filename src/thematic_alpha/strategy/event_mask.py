"""Earnings event mask (SPEC §1C, §5.4).

``blocked.loc[t, ticker]`` is True when a known earnings date falls within
``block_days_before_earnings`` sessions at or after ``t`` (the release day itself included, since
a signal at ``t`` executes at ``t + lag``). A ticker with no rows in ``earnings_dates.csv``
**fails open** — never masked — and is reported in ``failed_open`` with a logged warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("thematic_alpha.strategy.event_mask")


@dataclass
class EventMask:
    blocked: pd.DataFrame  # date x ticker bool
    failed_open: list[str] = field(default_factory=list)

    @property
    def masked_ticker_dates(self) -> int:
        return int(self.blocked.to_numpy().sum())


def load_earnings_dates(path: str | Path) -> dict[str, pd.DatetimeIndex]:
    df = pd.read_csv(path, comment="#", dtype=str)
    if df.empty:
        return {}
    df["ticker"] = df["ticker"].str.strip()
    df["earnings_date"] = pd.to_datetime(df["earnings_date"].str.strip(), errors="raise")
    return {
        t: pd.DatetimeIndex(sorted(set(g["earnings_date"])))
        for t, g in df.groupby("ticker", sort=True)
    }


def build_event_mask(
    dates: pd.DatetimeIndex,
    tickers: list[str],
    earnings: dict[str, pd.DatetimeIndex],
    block_days: int,
) -> EventMask:
    blocked = pd.DataFrame(False, index=dates, columns=tickers)
    failed_open: list[str] = []
    pos = np.arange(len(dates))
    for t in tickers:
        events = earnings.get(t)
        if events is None or len(events) == 0:
            failed_open.append(t)
            continue
        # Map each event to the first session on/after it, then block [event-N, event].
        event_pos = dates.searchsorted(events, side="left")
        event_pos = event_pos[event_pos < len(dates)]
        col = np.zeros(len(dates), dtype=bool)
        for ep in event_pos:
            col[max(ep - block_days, 0) : ep + 1] = True
        blocked[t] = col
        _ = pos
    if failed_open:
        logger.warning(
            "event mask: no earnings dates for %s; failing open (no mask applied).", failed_open
        )
    return EventMask(blocked=blocked, failed_open=failed_open)
