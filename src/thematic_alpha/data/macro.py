"""FRED macro loader with Parquet caching (SPEC §5.3).

Uses FRED's keyless CSV endpoint (``fredgraph.csv?id=SERIES``) read directly with pandas —
``pandas-datareader`` is not used (its pinned release imports ``distutils``, removed in 3.12).

Rules (SPEC §5.3 / §8.4): observation date is the index; **forward-fill only**, never back-fill or
interpolate; series are shifted by the publication lag before any feature or gate sees them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from thematic_alpha.data.cache import cache_path, is_cache_fresh, read_cache, write_cache

logger = logging.getLogger("thematic_alpha.data.macro")

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

FRED_SERIES: dict[str, str] = {
    "DGS10": "10Y Treasury constant maturity (%)",
    "DGS2": "2Y Treasury constant maturity (%)",
    "T10Y2Y": "10Y-2Y spread (pp)",
    "VIXCLS": "CBOE VIX",
    "DCOILWTICO": "WTI crude spot ($/bbl)",
    "T10YIE": "10Y breakeven inflation (%)",
    "DFF": "Effective fed funds rate (%)",
    "DTB3": "3-month T-bill (%) — risk-free rate",
    "DTWEXBGS": "Broad dollar index",
    "DEXUSEU": "USD per EUR",
    "DEXKOUS": "KRW per USD",
}
FX_SERIES = ["DEXUSEU", "DEXKOUS"]


def _fetch(series_id: str) -> pd.DataFrame:
    """Download one FRED series as a single-column frame indexed by observation date."""
    url = FRED_CSV_URL.format(sid=series_id)
    df = pd.read_csv(url, na_values=["."])
    date_col = df.columns[0]  # "observation_date" (current) or "DATE" (older exports)
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    df.index.name = "date"
    if series_id not in df.columns:
        raise ValueError(f"FRED response for {series_id} lacks a {series_id} column: {df.columns}")
    return df[[series_id]].astype(float)


def load_series(
    series_id: str,
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
) -> pd.Series:
    path = cache_path(cache_dir, "macro", series_id)
    if not refresh and is_cache_fresh(path, max_cache_age_days):
        df = read_cache(path)
        source = "cache"
    else:
        df = _fetch(series_id)
        if df.empty:
            logger.warning("%s: FRED returned no rows; not caching.", series_id)
        else:
            write_cache(path, df)
        source = "download"
    s = df[series_id]
    if len(s):
        logger.info(
            "%s: obs=%d first=%s last=%s nan=%d source=%s",
            series_id,
            len(s),
            s.index.min().date(),
            s.index.max().date(),
            int(s.isna().sum()),
            source,
        )
    return s


def load_macro(
    series_ids: list[str],
    cache_dir: str | Path,
    max_cache_age_days: int,
    refresh: bool = False,
) -> pd.DataFrame:
    """Outer-join several FRED series into one date-indexed frame (raw observation dates)."""
    cols = [load_series(sid, cache_dir, max_cache_age_days, refresh) for sid in series_ids]
    return pd.concat(cols, axis=1).sort_index()


def align_macro(df: pd.DataFrame, master: pd.DatetimeIndex, lag: int) -> pd.DataFrame:
    """Reindex onto the master calendar with forward-fill only, then shift by ``lag`` sessions.

    Forward-filling is done on the union of observation dates and master sessions so an
    observation on a non-session day (e.g. Good Friday) still carries into the next session.
    Leading NaNs stay NaN: nothing is back-filled.
    """
    union = df.index.union(master)
    out = df.reindex(union).ffill().reindex(master)
    if lag:
        out = out.shift(lag)
    return out
