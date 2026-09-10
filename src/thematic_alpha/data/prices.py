"""Price data loader with Parquet caching (SPEC §5.2).

Fetches daily OHLCV (plus adjusted close) from yfinance, caches each ticker to
``data/cache/prices/{ticker}.parquet``, and reloads from cache when fresh. yfinance is imported
lazily inside ``_fetch`` so cache-only paths (and the offline test suite) need neither network nor
the yfinance package.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger("thematic_alpha.data.prices")

# Columns we persist for every ticker. auto_adjust=False keeps raw Close AND Adj Close.
EXPECTED_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


@dataclass
class TickerReport:
    """Per-ticker data summary logged on load (SPEC §5.2)."""

    ticker: str
    first_date: pd.Timestamp | None
    last_date: pd.Timestamp | None
    rows: int
    missing_business_days: int
    from_cache: bool

    def log(self) -> None:
        first = self.first_date.date() if self.first_date is not None else "n/a"
        last = self.last_date.date() if self.last_date is not None else "n/a"
        source = "cache" if self.from_cache else "download"
        logger.info(
            "%s: rows=%d first=%s last=%s missing_bdays~%d (bdate_range proxy; "
            "true exchange calendar arrives in Layer 1) source=%s",
            self.ticker,
            self.rows,
            first,
            last,
            self.missing_business_days,
            source,
        )


def _cache_path(cache_dir: str | Path, ticker: str) -> Path:
    return Path(cache_dir) / "prices" / f"{ticker}.parquet"


def _is_cache_fresh(path: Path, max_cache_age_days: int) -> bool:
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_cache_age_days * 86400


def _read_cache(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df


def _write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _fetch(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    """Download daily bars from yfinance. Imported lazily so offline paths never touch it."""
    import yfinance as yf

    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        progress=False,
        actions=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        # Single-ticker downloads can come back with a (field, ticker) column MultiIndex.
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in EXPECTED_COLUMNS if c in df.columns]
    df = df[keep]
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    return df


def _ticker_report(ticker: str, df: pd.DataFrame, from_cache: bool) -> TickerReport:
    if df.empty:
        return TickerReport(ticker, None, None, 0, 0, from_cache)
    first, last = df.index.min(), df.index.max()
    # Interim missing-day proxy until Layer 1's calendar.py provides real exchange sessions.
    expected_bdays = len(pd.bdate_range(first, last))
    missing = max(expected_bdays - len(df), 0)
    return TickerReport(ticker, first, last, len(df), missing, from_cache)


def load_ticker(
    ticker: str,
    start: str,
    end: str | None,
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
) -> tuple[pd.DataFrame, TickerReport]:
    """Load one ticker, using the Parquet cache when fresh, else downloading and caching it."""
    path = _cache_path(cache_dir, ticker)
    use_cache = not refresh and _is_cache_fresh(path, max_cache_age_days)

    if use_cache:
        df = _read_cache(path)
        from_cache = True
    else:
        df = _fetch(ticker, start, end)
        if df.empty:
            logger.warning("%s: download returned no rows; not caching.", ticker)
        else:
            _write_cache(path, df)
        from_cache = False

    report = _ticker_report(ticker, df, from_cache)
    report.log()
    return df, report


def load_prices(
    tickers: list[str],
    start: str,
    end: str | None,
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load several tickers into a dict of frames, caching each to Parquet."""
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df, _ = load_ticker(ticker, start, end, cache_dir, max_cache_age_days, refresh)
        out[ticker] = df
    return out
