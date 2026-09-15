"""Synthetic markets for offline tests. Deterministic; no network.

Two-ticker market (``make_market``): ``AAA`` (NYSE, trades every master day), ``BBB`` (KRX, closed
every 37th master day), ``^GSPC`` (the market). Macro is a set of random walks already on the
master calendar.

Wide market (``make_wide_market``): twelve tickers with a ``segment`` each (two of them
``defensive``), one on the KRX-style calendar, two listing mid-sample so eligibility changes
inside the backtest window, one illiquid name, macro paths that trip every sub-gate, and
synthetic earnings dates every 63 sessions. ``make_bundle`` wraps either market in a
``pipeline.DataBundle`` so tests can drive the real pipeline stages end to end.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yaml

from tests.conftest import PROJECT_ROOT
from thematic_alpha.config import Config
from thematic_alpha.data.macro import FRED_SERIES, FX_SERIES
from thematic_alpha.data.prices import PricePanel, build_price_panel
from thematic_alpha.data.universe import Universe

TICKERS = ["AAA", "BBB"]
MARKET = "^GSPC"

WIDE_TICKERS = [f"W{i:02d}" for i in range(1, 13)]
WIDE_SEGMENTS = dict(
    zip(
        WIDE_TICKERS,
        [
            "compute",
            "hyperscaler",
            "memory",
            "optical",
            "hardware",
            "memory",
            "defensive",
            "defensive",
            "neocloud",
            "compute",
            "hyperscaler",
            "optical",
        ],
        strict=True,
    )
)
WIDE_KRX = "W06"  # closed every 37th master day
WIDE_ILLIQUID = "W03"  # tiny volume: the liquidity screen binds here and nowhere else
WIDE_LISTING = {"W11": 300, "W12": 500}  # first bar at this master position (mid-sample IPOs)


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
    segment_of: dict[str, str] | None = None
    earnings: dict[str, pd.DatetimeIndex] | None = None

    @property
    def tickers(self) -> list[str]:
        return [t for t in self.panel.tickers if t != MARKET]


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
        segment_of=market.segment_of,
        earnings=market.earnings,
    )


def _macro_frame(master: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    n = len(master)
    macro = pd.DataFrame(index=master)
    for k, sid in enumerate(FRED_SERIES):
        level = {"VIXCLS": 18.0, "DCOILWTICO": 60.0, "DTB3": 2.0, "DGS10": 2.5}.get(sid, 1.0 + k)
        macro[sid] = level + np.cumsum(rng.normal(0, 0.02 * level, n))
    macro["DTWEXBGS"] = 100 + np.cumsum(rng.normal(0, 0.3, n))
    macro["DEXUSEU"] = 1.1 + np.cumsum(rng.normal(0, 0.002, n))
    macro["DEXKOUS"] = 1200 + np.cumsum(rng.normal(0, 3, n))
    return macro


def make_wide_market(n_days: int = 900, seed: int = 1, start: str = "2018-01-01") -> Market:
    """Twelve-ticker market with segments, staggered listings and gate-tripping macro paths."""
    rng = np.random.default_rng(seed)
    master = pd.bdate_range(start, periods=n_days, name="date")
    krx_closed = master[36::37]
    sessions_of = {t: master for t in WIDE_TICKERS}
    sessions_of[WIDE_KRX] = master.difference(krx_closed)
    sessions_of[MARKET] = master

    common = rng.normal(0.0003, 0.010, n_days)
    raw = {}
    for i, t in enumerate(WIDE_TICKERS):
        idx = sessions_of[t]
        pos = master.get_indexer(idx)
        n = len(idx)
        # Heterogeneous drift plus a slow, phase-shifted cycle so momentum leadership rotates.
        drift = 0.0002 + 0.0003 * np.sin(i)
        cycle = 0.0015 * np.sin(2 * np.pi * (np.arange(n) / 250 + i / 12))
        r = drift + cycle + 0.8 * common[pos] + rng.normal(0, 0.015, n)
        close = 50.0 * (1 + i) * np.exp(np.cumsum(r))
        volume = 1e3 if t == WIDE_ILLIQUID else 2e5 * (1 + i)
        df = _ohlcv(idx, close, volume)
        if t in WIDE_LISTING:
            df = df.loc[df.index >= master[WIDE_LISTING[t]]]
        raw[t] = df
    raw[MARKET] = _ohlcv(master, 1000.0 * np.exp(np.cumsum(common)), volume=5e6)
    panel = build_price_panel(raw, master, sessions_of)

    macro = _macro_frame(master, rng)
    # VIX: mean-reverting around 17 with two spikes above the 25 threshold.
    vix = np.empty(n_days)
    vix[0] = 17.0
    eps = rng.normal(0, 0.8, n_days)
    for k in range(1, n_days):
        vix[k] = 17.0 + 0.9 * (vix[k - 1] - 17.0) + eps[k]
    vix[380:430] += 15.0
    vix[700:725] += 10.0
    macro["VIXCLS"] = np.clip(vix, 9.0, None)
    # 10y yield: random walk plus a 60 bp ramp over 30 sessions (21d change > 40 bp).
    dgs10 = 2.5 + np.cumsum(rng.normal(0, 0.015, n_days))
    dgs10[500:530] += np.linspace(0, 0.6, 30)
    dgs10[530:] += 0.6
    macro["DGS10"] = dgs10
    # WTI: random walk plus a +30% ramp over 30 sessions (21d change > 20%).
    wti = 60.0 * np.exp(np.cumsum(rng.normal(0, 0.008, n_days)))
    ramp = np.ones(n_days)
    ramp[200:230] = np.linspace(1.0, 1.3, 30)
    ramp[230:] = 1.3
    macro["DCOILWTICO"] = wti * ramp

    earnings = {t: pd.DatetimeIndex(master[40 + 5 * i :: 63]) for i, t in enumerate(WIDE_TICKERS)}
    return Market(
        master=master,
        sessions_of=sessions_of,
        raw=raw,
        panel=panel,
        dollar_volume=panel.close * panel.volume,
        macro=macro,
        currency_of={t: "USD" for t in [*WIDE_TICKERS, MARKET]},
        segment_of=dict(WIDE_SEGMENTS),
        earnings=earnings,
    )


def write_earnings_csv(earnings: dict[str, pd.DatetimeIndex], path) -> None:
    rows = [(t, d.strftime("%Y-%m-%d")) for t, dates in earnings.items() for d in dates]
    pd.DataFrame(rows, columns=["ticker", "earnings_date"]).to_csv(path, index=False)


def make_bundle(market: Market, benchmarks: list[str] | None = None):
    """Wrap a synthetic market in a ``pipeline.DataBundle`` (all-USD, macro treated as lagged)."""
    from thematic_alpha.pipeline import DataBundle

    benchmarks = benchmarks or [MARKET]
    tickers = market.tickers
    segment_of = market.segment_of or {t: "synthetic" for t in tickers}
    frame = pd.DataFrame(
        {
            "ticker": tickers,
            "name": tickers,
            "segment": [segment_of[t] for t in tickers],
            "exchange": ["KRX" if t in ("BBB", WIDE_KRX) else "NYSE" for t in tickers],
            "currency": [market.currency_of[t] for t in tickers],
            "regime_start_date": pd.NaT,
            "notes": None,
        }
    )
    universe = Universe(frame)
    exchange_of = dict(universe.exchange_of)
    for b in benchmarks:
        exchange_of.setdefault(b, "NYSE")
    return DataBundle(
        universe=universe,
        benchmarks=benchmarks,
        master=market.master,
        sessions_of=dict(market.sessions_of),
        exchange_of=exchange_of,
        raw_prices=dict(market.raw),
        reports=[],
        panel=market.panel,
        macro_raw=market.macro,
        macro=market.macro,
        fx=market.macro[FX_SERIES],
    )


# Layer 1 values of every knob that later layers add. The golden regression test pins these
# explicitly so it keeps reproducing Layer 1 after the YAML configs move to the chosen values.
LAYER1_NEUTRAL: dict[str, dict] = {
    "ranker": {"weighting": "conviction_tier", "exit_rank": None},
    "macro_gate": {"enabled": True, "combination": "multiplicative"},
    "event_mask": {"enabled": True, "block_new_entries_only": True},
    "turnover": {"position_band": 0.0},
}

# The chosen (preregistered) values of the same knobs, for tests that must pass with them on.
CHOSEN: dict[str, dict] = {
    "ranker": {"weighting": "equal", "exit_rank": 8},
    "turnover": {"position_band": 0.02},
}


def deep_merge(base: dict, overrides: dict) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for section, values in overrides.items():
        if isinstance(values, dict) and isinstance(out.get(section), dict):
            out[section] = {**out[section], **values}
        else:
            out[section] = values
    return out


def wide_config(**overrides) -> Config:
    """Config for the wide market: Layer 1 settings, USD base, window inside the sample."""
    with open(PROJECT_ROOT / "configs" / "base.yaml") as fh:
        raw = yaml.safe_load(fh)
    synthetic = {
        "run": {"base_currency": "USD", "start_date": "2019-01-02", "end_date": "2021-06-11"},
        "universe": {"file": "n/a", "benchmarks": [MARKET]},
        "event_mask": {"file": "golden_earnings.csv"},
    }
    raw = deep_merge(deep_merge(deep_merge(raw, LAYER1_NEUTRAL), synthetic), overrides)
    return Config.model_validate(copy.deepcopy(raw))


def run_pipeline(market: Market, config: Config, root):
    """features -> strategy -> backtests through the real pipeline stages."""
    from thematic_alpha import pipeline

    bundle = make_bundle(market, list(config.universe.benchmarks))
    features = pipeline.build_features(bundle, config)
    strategy = pipeline.build_strategy(bundle, features, config, root)
    results = pipeline.run_backtests(bundle, features, strategy, config)
    return bundle, features, strategy, results
