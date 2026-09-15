"""Synthetic two-exchange market for offline tests. Deterministic; no network.

Tickers: ``AAA`` (NYSE, trades every master day), ``BBB`` (KRX, closed every 37th master day),
``^GSPC`` (the market). Macro is a set of random walks already on the master calendar.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yaml

from tests.conftest import PROJECT_ROOT
from thematic_alpha.config import Config
from thematic_alpha.data.macro import FRED_SERIES
from thematic_alpha.data.prices import PricePanel, build_price_panel

TICKERS = ["AAA", "BBB"]
MARKET = "^GSPC"


def make_config(**overrides) -> Config:
    """Base config with nested overrides, e.g. make_config(data={"min_history_days": 60})."""
    with open(PROJECT_ROOT / "configs" / "base.yaml") as fh:
        raw = yaml.safe_load(fh)
    for section, values in overrides.items():
        raw[section] = {**raw[section], **values}
    return Config.model_validate(copy.deepcopy(raw))


@dataclass
class Market:
    master: pd.DatetimeIndex
    sessions_of: dict[str, pd.DatetimeIndex]
    raw: dict[str, pd.DataFrame]  # per-ticker OHLCV on own sessions
    panel: PricePanel
    dollar_volume: pd.DataFrame
    macro: pd.DataFrame
    currency_of: dict[str, str]


def _ohlcv(index: pd.DatetimeIndex, close: np.ndarray, volume: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(len(index), volume),
        },
        index=index,
    )


def make_market(n_days: int = 700, seed: int = 0, start: str = "2019-01-01") -> Market:
    rng = np.random.default_rng(seed)
    master = pd.bdate_range(start, periods=n_days, name="date")
    krx_closed = master[36::37]
    sessions_of = {
        "AAA": master,
        "BBB": master.difference(krx_closed),
        MARKET: master,
    }
    raw = {}
    for i, t in enumerate(["AAA", "BBB", MARKET]):
        idx = sessions_of[t]
        drift, vol = (0.0004, 0.02) if t != MARKET else (0.0003, 0.01)
        close = 100.0 * (i + 1) * np.exp(np.cumsum(rng.normal(drift, vol, len(idx))))
        raw[t] = _ohlcv(idx, close, volume=1e6 * (i + 1))
    panel = build_price_panel(raw, master, sessions_of)
    dollar_volume = panel.close * panel.volume  # base == local currency in the synthetic world

    macro = pd.DataFrame(index=master)
    for k, sid in enumerate(FRED_SERIES):
        level = {"VIXCLS": 18.0, "DCOILWTICO": 60.0, "DTB3": 2.0, "DGS10": 2.5}.get(sid, 1.0 + k)
        macro[sid] = level + np.cumsum(rng.normal(0, 0.02 * level, n_days))
    macro["DTWEXBGS"] = 100 + np.cumsum(rng.normal(0, 0.3, n_days))
    macro["DEXUSEU"] = 1.1 + np.cumsum(rng.normal(0, 0.002, n_days))
    macro["DEXKOUS"] = 1200 + np.cumsum(rng.normal(0, 3, n_days))

    return Market(
        master=master,
        sessions_of=sessions_of,
        raw=raw,
        panel=panel,
        dollar_volume=dollar_volume,
        macro=macro,
        currency_of={"AAA": "USD", "BBB": "USD", MARKET: "USD"},
    )


def build_features(market: Market, config: Config):
    from thematic_alpha.features.build import build_feature_panel

    return build_feature_panel(
        prices=market.panel,
        dollar_volume_base=market.dollar_volume,
        macro=market.macro,
        sessions_of=market.sessions_of,
        master=market.master,
        tickers=TICKERS,
        config=config,
        market_ticker=MARKET,
    )


def truncate(market: Market, t: pd.Timestamp) -> Market:
    """The same market with every input cut off after ``t`` (inclusive)."""
    master = market.master[market.master <= t]
    sessions_of = {k: v[v <= t] for k, v in market.sessions_of.items()}
    raw = {k: df.loc[:t] for k, df in market.raw.items()}
    panel = build_price_panel(raw, master, sessions_of)
    return Market(
        master=master,
        sessions_of=sessions_of,
        raw=raw,
        panel=panel,
        dollar_volume=market.dollar_volume.loc[:t],
        macro=market.macro.loc[:t],
        currency_of=market.currency_of,
    )
