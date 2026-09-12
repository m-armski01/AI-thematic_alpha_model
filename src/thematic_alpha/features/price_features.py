"""Per-ticker price features (SPEC §1B).

Every function takes wide ``date x ticker`` frames and returns wide frames. Rolling windows use
``min_periods == window`` so an incomplete window yields NaN — never an imputed value.

Calendar rule: features are computed on each ticker's **own** exchange sessions (so a 21-day
window is 21 real trading days), then aligned back onto the master calendar with forward-fill on
the ticker's non-session days. KRX closes before NYSE opens on the same date, so same-date
alignment introduces no lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.data.calendar import align_to_master

RETURN_HORIZONS = [1, 5, 21, 63, 126, 252]
ANNUALIZATION = 252
DOLLAR_VOLUME_WINDOW = 21
HIGH_WINDOW = 252


@dataclass(frozen=True)
class PriceFeatureSpec:
    momentum_windows: list[int]
    vol_windows: list[int]
    ma_windows: list[int]
    skip_recent_days: int
    beta_window: int


def returns(px: pd.DataFrame, horizons: list[int] = RETURN_HORIZONS) -> dict[str, pd.DataFrame]:
    return {f"ret_{h}d": px.pct_change(h, fill_method=None) for h in horizons}


def momentum(px: pd.DataFrame, windows: list[int], skip: int) -> dict[str, pd.DataFrame]:
    """Return from t-w to t-skip: ``px.shift(skip) / px.shift(w) - 1`` (reversal control)."""
    out = {}
    for w in windows:
        if w <= skip:
            raise ValueError(f"momentum window {w} must exceed skip_recent_days={skip}")
        out[f"mom_{w}"] = px.shift(skip) / px.shift(w) - 1
    return out


def realized_vol(px: pd.DataFrame, windows: list[int]) -> dict[str, pd.DataFrame]:
    r = px.pct_change(fill_method=None)
    return {
        f"vol_{w}": r.rolling(w, min_periods=w).std(ddof=1) * np.sqrt(ANNUALIZATION)
        for w in windows
    }


def price_to_ma(px: pd.DataFrame, windows: list[int]) -> dict[str, pd.DataFrame]:
    return {f"px_to_ma_{w}": px / px.rolling(w, min_periods=w).mean() - 1 for w in windows}


def dist_from_high(px: pd.DataFrame, window: int = HIGH_WINDOW) -> pd.DataFrame:
    return px / px.rolling(window, min_periods=window).max() - 1


def rolling_beta(px: pd.DataFrame, market_px: pd.Series, window: int) -> pd.DataFrame:
    """Rolling OLS beta of each column's 1-day returns on the market's 1-day returns."""
    r = px.pct_change(fill_method=None)
    m = market_px.pct_change(fill_method=None)
    cov = r.rolling(window, min_periods=window).cov(m)
    var = m.rolling(window, min_periods=window).var()
    return cov.div(var, axis=0)


def dollar_volume(dv: pd.DataFrame, window: int = DOLLAR_VOLUME_WINDOW) -> pd.DataFrame:
    return dv.rolling(window, min_periods=window).mean()


def history_days(px: pd.DataFrame) -> pd.DataFrame:
    """Cumulative count of observed sessions per ticker — the `min_history_days` screen input."""
    return px.notna().cumsum()


def compute_price_features_on_sessions(
    px: pd.DataFrame,
    dv_base: pd.DataFrame,
    market_px: pd.Series,
    spec: PriceFeatureSpec,
) -> dict[str, pd.DataFrame]:
    """All price features for frames that already sit on a single exchange's sessions."""
    feats: dict[str, pd.DataFrame] = {}
    feats.update(returns(px))
    feats.update(momentum(px, spec.momentum_windows, spec.skip_recent_days))
    feats.update(realized_vol(px, spec.vol_windows))
    feats.update(price_to_ma(px, spec.ma_windows))
    feats["dist_from_252d_high"] = dist_from_high(px)
    feats[f"beta_{spec.beta_window}d"] = rolling_beta(px, market_px, spec.beta_window)
    feats["dollar_volume_21d"] = dollar_volume(dv_base)
    feats["history_days"] = history_days(px)
    return feats


def compute_price_features(
    adj_close: pd.DataFrame,
    dollar_volume_base: pd.DataFrame,
    market_adj_close: pd.Series,
    sessions_of: dict[str, pd.DatetimeIndex],
    master: pd.DatetimeIndex,
    tickers: list[str],
    spec: PriceFeatureSpec,
) -> dict[str, pd.DataFrame]:
    """Compute features per exchange-session group, then align each onto ``master``.

    ``adj_close``/``dollar_volume_base``/``market_adj_close`` are on ``master`` (as produced by
    ``build_price_panel``); the market series is forward-filled so it is defined on every session
    of every exchange.
    """
    # Group tickers that share an identical session index so each group is one vectorized pass.
    groups: dict[tuple, list[str]] = {}
    for t in tickers:
        key = tuple(sessions_of[t].asi8)
        groups.setdefault(key, []).append(t)

    per_feature: dict[str, list[pd.DataFrame]] = {}
    market_ff = market_adj_close.reindex(master).ffill()
    for key, members in groups.items():
        sessions = pd.DatetimeIndex(np.asarray(key, dtype="datetime64[ns]"))
        sessions = sessions[sessions.isin(master)]
        px = adj_close.loc[sessions, members]
        dv = dollar_volume_base.loc[sessions, members]
        mkt = market_ff.loc[sessions]
        feats = compute_price_features_on_sessions(px, dv, mkt, spec)
        for name, frame in feats.items():
            per_feature.setdefault(name, []).append(align_to_master(frame, sessions, master))

    return {name: pd.concat(parts, axis=1)[tickers] for name, parts in per_feature.items()}
