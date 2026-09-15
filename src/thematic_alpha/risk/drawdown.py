"""Drawdowns (SPEC §1E): underwater series and a table of the largest episodes.

An episode starts the day after a running-high (the *peak*), bottoms at the *trough*, and ends
on the first day equity is back at or above the peak (the *recovery*; NaT if still underwater).
Duration is peak -> recovery (or -> last date) in calendar days.
"""

from __future__ import annotations

import pandas as pd


def underwater(equity: pd.Series) -> pd.Series:
    return (equity / equity.cummax() - 1.0).rename("underwater")


def drawdown_episodes(equity: pd.Series) -> pd.DataFrame:
    uw = underwater(equity)
    episodes = []
    in_dd = False
    peak = trough = None
    for date, depth in uw.items():
        if depth < 0 and not in_dd:
            in_dd = True
            peak = uw.index[uw.index.get_loc(date) - 1]
            trough, trough_depth = date, depth
        elif depth < 0 and in_dd:
            if depth < trough_depth:
                trough, trough_depth = date, depth
        elif depth >= 0 and in_dd:
            episodes.append((trough_depth, peak, trough, date))
            in_dd = False
    if in_dd:
        episodes.append((trough_depth, peak, trough, pd.NaT))
    df = pd.DataFrame(episodes, columns=["depth", "peak", "trough", "recovery"])
    end = pd.Timestamp(equity.index[-1])
    df["duration_days"] = [
        int(((r if pd.notna(r) else end) - p).days)
        for p, r in zip(df["peak"], df["recovery"], strict=True)
    ]
    return df.sort_values("depth").reset_index(drop=True)


def drawdown_table(equity: pd.Series, top: int = 5) -> pd.DataFrame:
    return drawdown_episodes(equity).head(top)


def max_drawdown(equity: pd.Series) -> dict:
    eps = drawdown_episodes(equity)
    if eps.empty:
        return {
            "depth": 0.0,
            "peak": pd.NaT,
            "trough": pd.NaT,
            "recovery": pd.NaT,
            "duration_days": 0,
        }
    row = eps.iloc[0]
    return {
        "depth": float(row["depth"]),
        "peak": row["peak"],
        "trough": row["trough"],
        "recovery": row["recovery"],
        "duration_days": int(row["duration_days"]),
    }
