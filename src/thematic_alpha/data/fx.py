"""Currency conversion (SPEC §1A / §1.1 "FX awareness").

FRED quotes ``DEXUSEU`` as USD per EUR and ``DEXKOUS`` as KRW per USD. Everything here is
expressed as *base currency per one unit of local currency*, so ``price_base = price_local * rate``.
Both local- and base-currency return streams are exposed so the FX contribution is separable.
"""

from __future__ import annotations

import pandas as pd

SUPPORTED = {"EUR", "USD", "KRW"}


def base_per_local(local: str, base: str, fx: pd.DataFrame) -> pd.Series:
    """Series of ``base`` units per one ``local`` unit, on ``fx``'s index."""
    if local not in SUPPORTED or base not in SUPPORTED:
        raise ValueError(f"unsupported currency pair {local}->{base}")
    ones = pd.Series(1.0, index=fx.index)
    if local == base:
        return ones
    usd_per_eur = fx["DEXUSEU"] if "DEXUSEU" in fx else None
    krw_per_usd = fx["DEXKOUS"] if "DEXKOUS" in fx else None

    def _need(s: pd.Series | None, name: str) -> pd.Series:
        if s is None:
            raise ValueError(f"fx frame lacks {name}, needed for {local}->{base}")
        return s

    if base == "EUR":
        if local == "USD":
            return 1.0 / _need(usd_per_eur, "DEXUSEU")
        if local == "KRW":
            return 1.0 / (_need(krw_per_usd, "DEXKOUS") * _need(usd_per_eur, "DEXUSEU"))
    if base == "USD":
        if local == "EUR":
            return _need(usd_per_eur, "DEXUSEU").astype(float)
        if local == "KRW":
            return 1.0 / _need(krw_per_usd, "DEXKOUS")
    if base == "KRW":
        if local == "USD":
            return _need(krw_per_usd, "DEXKOUS").astype(float)
        if local == "EUR":
            return _need(krw_per_usd, "DEXKOUS") * _need(usd_per_eur, "DEXUSEU")
    raise ValueError(f"unsupported currency pair {local}->{base}")  # pragma: no cover


def to_base(
    prices_local: pd.DataFrame,
    currency_of: dict[str, str],
    base: str,
    fx: pd.DataFrame,
) -> pd.DataFrame:
    """Convert a date x ticker price frame into ``base`` currency. ``fx`` must share the index."""
    fx = fx.reindex(prices_local.index)
    out = prices_local.copy()
    for ticker in prices_local.columns:
        rate = base_per_local(currency_of[ticker], base, fx)
        out[ticker] = prices_local[ticker] * rate
    return out


def local_and_base_returns(
    prices_local: pd.DataFrame,
    currency_of: dict[str, str],
    base: str,
    fx: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(local-currency returns, base-currency returns). Difference is the FX contribution."""
    ret_local = prices_local.pct_change(fill_method=None)
    ret_base = to_base(prices_local, currency_of, base, fx).pct_change(fill_method=None)
    return ret_local, ret_base
