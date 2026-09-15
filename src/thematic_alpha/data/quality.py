"""Data-quality report -> ``outputs/data_quality.md`` (SPEC §1A).

Per ticker: first/last date, rows, coverage vs its own exchange calendar, gap count, longest gap,
and every |1-day adjusted-close return| above the threshold (flagged for manual review against
corporate actions — nothing is auto-corrected). Per macro series: span, observations, NaNs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from thematic_alpha.data.calendar import longest_gap, missing_sessions


@dataclass
class TickerQuality:
    ticker: str
    exchange: str
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    rows: int
    own_sessions: int
    coverage: float
    gaps: int
    longest_gap: int
    suspicious: list[tuple[pd.Timestamp, float]]
    nonpositive_adj_close: int = 0


def ticker_quality(
    ticker: str,
    exchange: str,
    df: pd.DataFrame,
    own_sessions: pd.DatetimeIndex,
    threshold: float,
) -> TickerQuality:
    if df.empty:
        return TickerQuality(ticker, exchange, None, None, 0, 0, 0.0, 0, 0, [])
    first, last = df.index.min(), df.index.max()
    span = own_sessions[(own_sessions >= first) & (own_sessions <= last)]
    coverage = len(df.index.intersection(span)) / len(span) if len(span) else 0.0
    ret = df["Adj Close"].pct_change(fill_method=None)
    flagged = ret[ret.abs() > threshold]
    return TickerQuality(
        ticker=ticker,
        exchange=exchange,
        first=first,
        last=last,
        rows=len(df),
        own_sessions=len(span),
        coverage=coverage,
        gaps=missing_sessions(df.index, own_sessions),
        longest_gap=longest_gap(df.index, own_sessions),
        suspicious=[(d, float(r)) for d, r in flagged.items()],
        nonpositive_adj_close=int((df["Adj Close"] <= 0).sum()),
    )


def _fmt_date(ts: pd.Timestamp | None) -> str:
    return ts.strftime("%Y-%m-%d") if ts is not None else "n/a"


def render_quality_report(
    tickers: list[TickerQuality],
    macro: pd.DataFrame,
    threshold: float,
) -> str:
    lines = ["# Data quality report", ""]
    lines.append(
        "Coverage is measured against each ticker's **own** exchange calendar "
        "(`exchange_calendars`: XNYS for NASDAQ/NYSE, XKRX for KRX). Gaps are own-exchange "
        "sessions with no bar. Suspicious returns are flagged for manual review against corporate "
        "actions; nothing is auto-corrected."
    )
    lines += ["", "## Price series", ""]
    lines.append(
        "| ticker | exchange | first | last | rows | sessions | coverage | gaps | longest gap | "
        f"flags (>{threshold:.0%}) | adj close <= 0 |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for q in tickers:
        lines.append(
            f"| {q.ticker} | {q.exchange} | {_fmt_date(q.first)} | {_fmt_date(q.last)} | "
            f"{q.rows} | {q.own_sessions} | {q.coverage:.1%} | {q.gaps} | {q.longest_gap} | "
            f"{len(q.suspicious)} | {q.nonpositive_adj_close} |"
        )
    lines += ["", f"## Suspicious 1-day returns (|r| > {threshold:.0%})", ""]
    any_flag = False
    for q in tickers:
        for d, r in q.suspicious:
            any_flag = True
            lines.append(f"- {q.ticker} {_fmt_date(d)}: {r:+.1%}")
    if not any_flag:
        lines.append("None.")
    lines += ["", "## Macro series (FRED, raw observation dates)", ""]
    lines.append("| series | first | last | obs | NaN within span |")
    lines.append("|---|---|---|---:|---:|")
    for col in macro.columns:
        s = macro[col].dropna()
        first = s.index.min() if len(s) else None
        last = s.index.max() if len(s) else None
        # NaNs only between the series' own first and last observation ("." entries in FRED).
        within = macro[col].loc[first:last] if len(s) else macro[col].iloc[0:0]
        lines.append(
            f"| {col} | {_fmt_date(first)} | {_fmt_date(last)} | {len(s)} | "
            f"{int(within.isna().sum())} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_quality_report(text: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
