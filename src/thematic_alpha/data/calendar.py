"""Trading-day alignment across exchanges (SPEC §5.4, "cross-exchange calendars").

The master calendar is the **union** of every exchange's sessions. A ticker's frame is reindexed
onto it and forward-filled *only* on dates that are not sessions of its own exchange (a KRX
holiday for SK Hynix, say). A date that *is* one of its own sessions but has no data stays NaN, so
a return is never computed across a real data gap as if it were a single day.
"""

from __future__ import annotations

import pandas as pd

# universe.csv exchange labels -> ISO 10383 MIC used by exchange_calendars. Every US venue
# (NYSE, NYSE Arca, NASDAQ, Cboe BZX) keeps the NYSE trading calendar, so they all map to XNYS.
EXCHANGE_TO_MIC = {
    "NASDAQ": "XNYS",
    "NYSE": "XNYS",
    "NYSE Arca": "XNYS",
    "Cboe BZX": "XNYS",
    "KRX": "XKRX",
}
BENCHMARK_MIC = "XNYS"


def mic_for(exchange: str) -> str:
    try:
        return EXCHANGE_TO_MIC[exchange]
    except KeyError as exc:
        raise ValueError(
            f"unknown exchange {exchange!r}; add it to calendar.EXCHANGE_TO_MIC"
        ) from exc


def exchange_sessions(mic: str, start: str, end: str | None = None) -> pd.DatetimeIndex:
    """Sessions of one exchange in [start, end] as tz-naive midnight timestamps."""
    import exchange_calendars as xc

    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    # The calendar is built for exactly [start, end]; `.sessions` is every session inside it.
    # (sessions_in_range would reject a `start` that is not itself a session, e.g. Jan 1.)
    cal = xc.get_calendar(mic, start=pd.Timestamp(start), end=end_ts)
    sessions = cal.sessions
    return pd.DatetimeIndex(sessions.tz_localize(None) if sessions.tz is not None else sessions)


def master_calendar(session_sets: list[pd.DatetimeIndex]) -> pd.DatetimeIndex:
    """Union of session sets, sorted."""
    if not session_sets:
        raise ValueError("master_calendar needs at least one session set")
    out = session_sets[0]
    for s in session_sets[1:]:
        out = out.union(s)
    return pd.DatetimeIndex(out).sort_values()


def align_to_master(
    df: pd.DataFrame, own_sessions: pd.DatetimeIndex, master: pd.DatetimeIndex
) -> pd.DataFrame:
    """Reindex onto ``master``; forward-fill only on non-own-session dates. Never back-fill."""
    out = df.reindex(master)
    if out.empty:
        return out
    non_own = ~master.isin(own_sessions)
    filled = out.ffill()
    out.loc[non_own] = filled.loc[non_own]
    # Nothing before the ticker's first observation is ever filled (no back-fill).
    first = df.index.min() if len(df) else None
    if first is not None:
        out.loc[master < first] = float("nan")
    return out


def missing_sessions(index: pd.DatetimeIndex, own_sessions: pd.DatetimeIndex) -> int:
    """Count of own-exchange sessions between first and last observed date that have no row."""
    if len(index) == 0:
        return 0
    span = own_sessions[(own_sessions >= index.min()) & (own_sessions <= index.max())]
    return int((~span.isin(index)).sum())


def longest_gap(index: pd.DatetimeIndex, own_sessions: pd.DatetimeIndex) -> int:
    """Longest run of consecutive missing own-exchange sessions within the observed span."""
    if len(index) == 0:
        return 0
    span = own_sessions[(own_sessions >= index.min()) & (own_sessions <= index.max())]
    present = span.isin(index)
    best = run = 0
    for p in present:
        run = 0 if p else run + 1
        best = max(best, run)
    return int(best)
