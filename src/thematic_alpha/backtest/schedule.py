"""Rebalance schedule: which sessions are *signal* dates.

Weekly: the last session in each ISO week whose weekday is on or before ``rebalance_day``
(a Friday holiday rolls back to Thursday); if no such session exists, the week's first session.
Monthly: the last weekly signal date of each calendar month.

``sessions`` should be the primary exchange's sessions (NYSE), not the master union, so a
signal is never generated on a day when the US names did not trade.
"""

from __future__ import annotations

import pandas as pd

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}


def signal_dates(
    sessions: pd.DatetimeIndex,
    rebalance: str,
    rebalance_day: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DatetimeIndex:
    target = WEEKDAYS[rebalance_day]
    s = pd.Series(sessions, index=sessions)
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    iso = s.index.isocalendar()
    picks = []
    for _, grp in s.groupby([iso["year"].to_numpy(), iso["week"].to_numpy()], sort=False):
        on_or_before = grp[grp.index.weekday <= target]
        picks.append(on_or_before.index[-1] if len(on_or_before) else grp.index[0])
    out = pd.DatetimeIndex(sorted(picks))
    if rebalance == "monthly":
        ser = pd.Series(out, index=out)
        out = pd.DatetimeIndex(ser.groupby([out.year, out.month]).last().to_numpy())
    return out
