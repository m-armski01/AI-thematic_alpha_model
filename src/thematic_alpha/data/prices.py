"""Price data loader with Parquet caching (SPEC §5.2).

Fetches daily OHLCV (plus adjusted close) from yfinance, caches each ticker to
``data/cache/prices/{ticker}.parquet``, and reloads from cache when fresh. yfinance is imported
lazily inside ``_fetch`` so cache-only paths (and the offline test suite) need neither network nor
the yfinance package. ``build_price_panel`` turns the per-ticker frames into wide date x ticker
frames aligned onto the master trading calendar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from thematic_alpha.data import cache as _cache
from thematic_alpha.data.calendar import align_to_master, missing_sessions

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
    missing_sessions: int
    from_cache: bool

    def log(self) -> None:
        first = self.first_date.date() if self.first_date is not None else "n/a"
        last = self.last_date.date() if self.last_date is not None else "n/a"
        source = "cache" if self.from_cache else "download"
        logger.info(
            "%s: rows=%d first=%s last=%s missing_sessions=%d source=%s",
            self.ticker,
            self.rows,
            first,
            last,
            self.missing_sessions,
            source,
        )


# Thin aliases kept so callers/tests that used the Layer 0 names keep working.
def _cache_path(cache_dir: str | Path, ticker: str) -> Path:
    return _cache.cache_path(cache_dir, "prices", ticker)


_is_cache_fresh = _cache.is_cache_fresh
_read_cache = _cache.read_cache
_write_cache = _cache.write_cache


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


def _ticker_report(
    ticker: str,
    df: pd.DataFrame,
    from_cache: bool,
    own_sessions: pd.DatetimeIndex | None = None,
) -> TickerReport:
    if df.empty:
        return TickerReport(ticker, None, None, 0, 0, from_cache)
    first, last = df.index.min(), df.index.max()
    if own_sessions is None:
        # No calendar supplied: fall back to a weekday proxy.
        own_sessions = pd.bdate_range(first, last)
    missing = missing_sessions(df.index, own_sessions)
    return TickerReport(ticker, first, last, len(df), missing, from_cache)


def load_ticker(
    ticker: str,
    start: str,
    end: str | None,
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
    own_sessions: pd.DatetimeIndex | None = None,
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

    # Tolerate short series (SPEC §5.2): a ticker with fewer rows than requested is fine.
    df = df.loc[df.index >= pd.Timestamp(start)] if not df.empty else df
    report = _ticker_report(ticker, df, from_cache, own_sessions)
    report.log()
    return df, report


def load_prices(
    tickers: list[str],
    start: str,
    end: str | None,
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
    sessions_of: dict[str, pd.DatetimeIndex] | None = None,
) -> tuple[dict[str, pd.DataFrame], list[TickerReport]]:
    """Load several tickers into a dict of frames, caching each to Parquet."""
    out: dict[str, pd.DataFrame] = {}
    reports: list[TickerReport] = []
    for ticker in tickers:
        own = sessions_of.get(ticker) if sessions_of else None
        df, report = load_ticker(ticker, start, end, cache_dir, max_cache_age_days, refresh, own)
        out[ticker] = df
        reports.append(report)
    return out, reports


def drop_phantom_bars(df: pd.DataFrame, own_sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Drop zero-volume bars dated on days the ticker's exchange was closed.

    yfinance emits stale, zero-volume "bars" on Korean holidays for KRX tickers (price copied
    from the previous session). They are not observations, so they are removed before alignment.
    A bar on a non-session day *with* volume is kept: the calendar library, not the data, may be
    wrong in that case.
    """
    if df.empty or "Volume" not in df.columns:
        return df
    phantom = ~df.index.isin(own_sessions) & (df["Volume"].fillna(0) == 0)
    return df.loc[~phantom]


@dataclass
class PricePanel:
    """Wide date x ticker frames in **local** currency, aligned onto the master calendar."""

    adj_close: pd.DataFrame
    adj_open: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    tickers: list[str] = field(default_factory=list)

    @property
    def index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.adj_close.index)


def build_price_panel(
    frames: dict[str, pd.DataFrame],
    master: pd.DatetimeIndex,
    sessions_of: dict[str, pd.DatetimeIndex],
) -> PricePanel:
    """Align each ticker onto ``master`` (ffill only on non-own sessions) and pivot wide.

    ``adj_open`` is ``Open * AdjClose / Close`` so open-price execution uses the same adjustment
    basis as the adjusted close.
    """
    cols: dict[str, dict[str, pd.Series]] = {
        "adj_close": {},
        "adj_open": {},
        "close": {},
        "vol": {},
    }
    tickers = [t for t, df in frames.items() if not df.empty]
    for t in tickers:
        df = frames[t]
        aligned = align_to_master(df, sessions_of[t], master)
        factor = aligned["Adj Close"] / aligned["Close"]
        cols["adj_close"][t] = aligned["Adj Close"]
        cols["adj_open"][t] = aligned["Open"] * factor
        cols["close"][t] = aligned["Close"]
        cols["vol"][t] = aligned["Volume"]
    mk = lambda d: pd.DataFrame(d, index=master, columns=tickers)  # noqa: E731
    return PricePanel(
        adj_close=mk(cols["adj_close"]),
        adj_open=mk(cols["adj_open"]),
        close=mk(cols["close"]),
        volume=mk(cols["vol"]),
        tickers=tickers,
    )
