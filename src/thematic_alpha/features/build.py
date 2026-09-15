"""Assemble the tidy feature panel: ``MultiIndex(date, ticker)`` (SPEC §1B).

Price features are stacked, macro features are broadcast to every ticker on each date, and the
cross-sectional ranks are computed over *eligible* names only. ``eligible`` is True when the
ticker has at least ``min_history_days`` observed sessions, its ranking inputs are non-NaN and,
when ``data.min_dollar_volume_21d`` > 0, its 21-day average traded value (base currency) is at
least that threshold.

Hard rule: every value at date ``t`` uses only data available at the close of ``t``. Enforced by
``tests/test_no_lookahead.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from thematic_alpha.config import Config
from thematic_alpha.data.prices import PricePanel
from thematic_alpha.features.macro_features import MacroFeatureSpec, compute_macro_features
from thematic_alpha.features.price_features import PriceFeatureSpec, compute_price_features

RANK_MOMENTUM = "mom_63"
RANK_VOL = "vol_21"


@dataclass
class FeaturePanel:
    tidy: pd.DataFrame  # MultiIndex(date, ticker) x features
    wide: dict[str, pd.DataFrame]  # feature -> date x ticker (universe tickers)
    macro: pd.DataFrame  # date x macro features
    eligible: pd.DataFrame  # date x ticker bool
    first_dates: pd.DataFrame | None = (
        None  # ticker x (first price / history / liquidity / eligible)
    )

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.eligible.index)


def eligibility(
    history_days: pd.DataFrame,
    min_history_days: int,
    *required: pd.DataFrame,
    dollar_volume_21d: pd.DataFrame | None = None,
    min_dollar_volume_21d: float = 0.0,
) -> pd.DataFrame:
    ok = history_days >= min_history_days
    for frame in required:
        ok &= frame.notna()
    if min_dollar_volume_21d > 0.0:
        if dollar_volume_21d is None:
            raise ValueError("min_dollar_volume_21d > 0 needs the dollar_volume_21d frame")
        ok &= dollar_volume_21d >= min_dollar_volume_21d
    return ok.fillna(False).astype(bool)


def _first_true(frame: pd.DataFrame) -> pd.Series:
    out = {}
    for t in frame.columns:
        col = frame[t].to_numpy(dtype=bool)
        out[t] = frame.index[int(col.argmax())] if col.any() else pd.NaT
    return pd.Series(out, dtype="datetime64[ns]")


def first_dates(
    adj_close: pd.DataFrame,
    history_days: pd.DataFrame,
    dollar_volume_21d: pd.DataFrame,
    eligible: pd.DataFrame,
    min_history_days: int,
    min_dollar_volume_21d: float,
) -> pd.DataFrame:
    """Per ticker: first price, first history-eligible, first liquidity-eligible, first eligible."""
    tickers = list(eligible.columns)
    liquidity = (
        (dollar_volume_21d[tickers] >= min_dollar_volume_21d).fillna(False)
        if min_dollar_volume_21d > 0.0
        else adj_close[tickers].notna()
    )
    return pd.DataFrame(
        {
            "first_price": _first_true(adj_close[tickers].notna()),
            "first_history_eligible": _first_true(
                (history_days[tickers] >= min_history_days).fillna(False)
            ),
            "first_liquidity_eligible": _first_true(liquidity),
            "first_eligible": _first_true(eligible[tickers]),
        }
    ).rename_axis("ticker")


def cross_sectional_rank(values: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank across eligible tickers on each date (NaN for ineligible)."""
    return values.where(eligible).rank(axis=1, pct=True)


def stack_features(wide: dict[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {name: frame.stack(future_stack=True) for name, frame in wide.items()}
    tidy = pd.DataFrame(cols)
    tidy.index = tidy.index.set_names(["date", "ticker"])
    return tidy


def broadcast_macro(tidy: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    dates = tidy.index.get_level_values("date")
    macro_rows = macro.reindex(dates)
    macro_rows.index = tidy.index
    return pd.concat([tidy, macro_rows], axis=1)


def build_feature_panel(
    prices: PricePanel,
    dollar_volume_base: pd.DataFrame,
    macro: pd.DataFrame,
    sessions_of: dict[str, pd.DatetimeIndex],
    master: pd.DatetimeIndex,
    tickers: list[str],
    config: Config,
    market_ticker: str,
) -> FeaturePanel:
    """``market_ticker`` is the beta reference: ``universe.benchmarks[0]`` in the pipeline."""
    if market_ticker not in prices.adj_close.columns:
        raise ValueError(f"market ticker {market_ticker!r} is not in the price panel")
    spec = PriceFeatureSpec(
        momentum_windows=config.features.momentum_windows,
        vol_windows=config.features.vol_windows,
        ma_windows=config.features.ma_windows,
        skip_recent_days=config.features.skip_recent_days,
        beta_window=config.risk.rolling_beta_window,
    )
    wide = compute_price_features(
        prices.adj_close,
        dollar_volume_base,
        prices.adj_close[market_ticker],
        sessions_of,
        master,
        tickers,
        spec,
    )
    if RANK_MOMENTUM not in wide or RANK_VOL not in wide:
        raise ValueError(
            f"config.features must include the ranking windows: {RANK_MOMENTUM}, {RANK_VOL}"
        )
    eligible = eligibility(
        wide["history_days"],
        config.data.min_history_days,
        wide[RANK_MOMENTUM],
        wide[RANK_VOL],
        dollar_volume_21d=wide["dollar_volume_21d"],
        min_dollar_volume_21d=config.data.min_dollar_volume_21d,
    )
    wide["eligible"] = eligible
    firsts = first_dates(
        prices.adj_close,
        wide["history_days"],
        wide["dollar_volume_21d"],
        eligible,
        config.data.min_history_days,
        config.data.min_dollar_volume_21d,
    )
    wide["mom_rank"] = cross_sectional_rank(wide[RANK_MOMENTUM], eligible)
    wide["vol_rank"] = cross_sectional_rank(wide[RANK_VOL], eligible)

    macro_feats = compute_macro_features(
        macro,
        MacroFeatureSpec(
            yield_change_window=config.macro_gate.yield_change_window,
            oil_change_window=config.macro_gate.oil_change_window,
        ),
    )
    tidy = broadcast_macro(stack_features(wide), macro_feats)
    return FeaturePanel(
        tidy=tidy, wide=wide, macro=macro_feats, eligible=eligible, first_dates=firsts
    )
