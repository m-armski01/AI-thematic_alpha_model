"""Pipeline stages. ``run.py`` stays thin; each stage here is a plain function on plain data.

Layer 1A: ``load_data`` -> ``DataBundle`` (prices on the master calendar, lagged macro, FX) and
``write_data_quality``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from thematic_alpha.backtest.schedule import signal_dates
from thematic_alpha.config import Config
from thematic_alpha.data import calendar as cal
from thematic_alpha.data import fx as fxmod
from thematic_alpha.data import macro as macromod
from thematic_alpha.data import quality
from thematic_alpha.data.prices import (
    PricePanel,
    TickerReport,
    build_price_panel,
    drop_phantom_bars,
    load_prices,
)
from thematic_alpha.data.universe import Universe, apply_regime_start, load_universe
from thematic_alpha.features.build import FeaturePanel, build_feature_panel
from thematic_alpha.strategy.compose import ComposeResult, compose_target_weights
from thematic_alpha.strategy.event_mask import EventMask, build_event_mask, load_earnings_dates
from thematic_alpha.strategy.macro_gate import gate_factors
from thematic_alpha.strategy.ranker import rank
from thematic_alpha.strategy.sizing import announce_house_money

logger = logging.getLogger("thematic_alpha.pipeline")


@dataclass
class DataBundle:
    universe: Universe
    benchmarks: list[str]
    master: pd.DatetimeIndex
    sessions_of: dict[str, pd.DatetimeIndex]  # ticker -> own exchange sessions
    exchange_of: dict[str, str]  # ticker -> exchange label (benchmarks -> "NYSE")
    raw_prices: dict[str, pd.DataFrame]  # per-ticker OHLCV, own calendar, local ccy
    reports: list[TickerReport]
    panel: PricePanel  # local currency, master calendar
    macro_raw: pd.DataFrame  # observation dates, no alignment
    macro: pd.DataFrame  # master calendar, ffill-only, lagged
    fx: pd.DataFrame  # master calendar, ffill-only, NOT lagged (valuation, not signal)

    @property
    def currency_of(self) -> dict[str, str]:
        out = dict(self.universe.currency_of)
        for b in self.benchmarks:
            out.setdefault(b, "USD")
        return out


def _end_date(config: Config) -> str:
    return config.run.end_date or pd.Timestamp.today().normalize().strftime("%Y-%m-%d")


def load_data(config: Config, root: Path, refresh: bool = False) -> DataBundle:
    universe = load_universe(root / config.universe.file)
    benchmarks = list(config.universe.benchmarks)
    cache_dir = root / "data" / "cache"
    start, end = config.data.history_start, _end_date(config)

    # --- calendars ----------------------------------------------------------------------------
    exchange_of = dict(universe.exchange_of)
    for b in benchmarks:
        exchange_of.setdefault(b, "NYSE")
    mics = sorted({cal.mic_for(ex) for ex in exchange_of.values()})
    sessions_by_mic = {mic: cal.exchange_sessions(mic, start, end) for mic in mics}
    master = cal.master_calendar(list(sessions_by_mic.values()))
    sessions_of = {t: sessions_by_mic[cal.mic_for(ex)] for t, ex in exchange_of.items()}
    logger.info(
        "master calendar: %d sessions %s -> %s (union of %s)",
        len(master),
        master.min().date(),
        master.max().date(),
        ", ".join(mics),
    )

    # --- prices -------------------------------------------------------------------------------
    tickers = universe.tickers + [b for b in benchmarks if b not in universe.tickers]
    raw, reports = load_prices(
        tickers,
        start,
        end,
        cache_dir,
        config.data.max_cache_age_days,
        refresh,
        sessions_of,
    )
    raw = apply_regime_start(raw, universe)
    for t, df in raw.items():
        cleaned = drop_phantom_bars(df, sessions_of[t])
        if len(cleaned) != len(df):
            logger.info(
                "%s: dropped %d zero-volume bars on non-session days", t, len(df) - len(cleaned)
            )
        raw[t] = cleaned
    empty = [t for t, df in raw.items() if df.empty]
    if empty:
        logger.warning("no data for %s; they are dropped from the panel.", empty)
    panel = build_price_panel(raw, master, sessions_of)

    # --- macro --------------------------------------------------------------------------------
    macro_raw = macromod.load_macro(
        list(macromod.FRED_SERIES), cache_dir, config.data.max_cache_age_days, refresh
    )
    macro = macromod.align_macro(macro_raw, master, config.data.macro_publication_lag_days)
    fx = macromod.align_macro(macro_raw[macromod.FX_SERIES], master, lag=0)

    return DataBundle(
        universe=universe,
        benchmarks=benchmarks,
        master=master,
        sessions_of=sessions_of,
        exchange_of=exchange_of,
        raw_prices=raw,
        reports=reports,
        panel=panel,
        macro_raw=macro_raw,
        macro=macro,
        fx=fx,
    )


def base_currency_prices(bundle: DataBundle, base: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(adj_close, adj_open) converted into ``base`` currency on the master calendar."""
    ccy = bundle.currency_of
    close = fxmod.to_base(bundle.panel.adj_close, ccy, base, bundle.fx)
    open_ = fxmod.to_base(bundle.panel.adj_open, ccy, base, bundle.fx)
    return close, open_


def dollar_volume_base(bundle: DataBundle, base: str) -> pd.DataFrame:
    """Close x Volume per ticker, converted into ``base`` currency (liquidity screen input)."""
    return fxmod.to_base(
        bundle.panel.close * bundle.panel.volume, bundle.currency_of, base, bundle.fx
    )


def build_features(bundle: DataBundle, config: Config) -> FeaturePanel:
    """Layer 1B: the tidy feature panel for the universe tickers (local-currency features)."""
    fp = build_feature_panel(
        prices=bundle.panel,
        dollar_volume_base=dollar_volume_base(bundle, config.run.base_currency),
        macro=bundle.macro,
        sessions_of=bundle.sessions_of,
        master=bundle.master,
        tickers=[t for t in bundle.universe.tickers if t in bundle.panel.tickers],
        config=config,
    )
    last = fp.eligible.index[-1]
    logger.info(
        "feature panel: %d rows x %d cols, %s -> %s, eligible on %s: %d/%d",
        len(fp.tidy),
        fp.tidy.shape[1],
        fp.dates.min().date(),
        fp.dates.max().date(),
        last.date(),
        int(fp.eligible.loc[last].sum()),
        fp.eligible.shape[1],
    )
    return fp


@dataclass
class StrategyBundle:
    signal_dates: pd.DatetimeIndex
    gate: pd.DataFrame  # date x (vix_factor, yield_factor, oil_factor, exposure), all dates
    ranker_weights: pd.DataFrame  # date x ticker, all dates
    event_mask: EventMask
    composed: ComposeResult

    @property
    def target_weights(self) -> pd.DataFrame:
        return self.composed.target_weights


def build_strategy(
    bundle: DataBundle, features: FeaturePanel, config: Config, root: Path
) -> StrategyBundle:
    """Layer 1C: gate + ranker + event mask + sizing -> target weights on signal dates."""
    market = config.universe.benchmarks[0]
    dates = signal_dates(
        bundle.sessions_of[market],
        config.backtest.rebalance,
        config.backtest.rebalance_day,
        start=config.run.start_date,
        end=config.run.end_date,
    )
    gate = gate_factors(features.macro, config.macro_gate)
    tickers = list(features.eligible.columns)
    ranker_weights = rank(features.wide, features.eligible, config.ranker)

    if config.event_mask.enabled:
        earnings = load_earnings_dates(root / config.event_mask.file)
        mask = build_event_mask(
            bundle.master, tickers, earnings, config.event_mask.block_days_before_earnings
        )
    else:
        mask = None
    announce_house_money(config.sizing)
    composed = compose_target_weights(ranker_weights, gate["exposure"], dates, config.sizing, mask)
    if mask is None:
        mask = EventMask(
            blocked=pd.DataFrame(False, index=bundle.master, columns=tickers), failed_open=[]
        )
    exp = composed.exposure
    logger.info(
        "strategy: %d signal dates %s -> %s | exposure mean=%.2f min=%.2f (<1 on %d dates) | "
        "avg names held=%.1f | avg invested=%.1f%%",
        len(dates),
        dates.min().date(),
        dates.max().date(),
        exp.mean(),
        exp.min(),
        int((exp < 1).sum()),
        (composed.target_weights > 0).sum(axis=1).mean(),
        100 * composed.target_weights.sum(axis=1).mean(),
    )
    return StrategyBundle(
        signal_dates=dates,
        gate=gate,
        ranker_weights=ranker_weights,
        event_mask=mask,
        composed=composed,
    )


def write_data_quality(bundle: DataBundle, config: Config, root: Path) -> Path:
    rows = [
        quality.ticker_quality(
            t,
            bundle.exchange_of[t],
            bundle.raw_prices[t],
            bundle.sessions_of[t],
            config.data.suspicious_return_threshold,
        )
        for t in bundle.raw_prices
    ]
    text = quality.render_quality_report(
        rows, bundle.macro_raw, config.data.suspicious_return_threshold
    )
    path = quality.write_quality_report(text, root / "outputs" / "data_quality.md")
    n_flags = sum(len(r.suspicious) for r in rows)
    logger.info(
        "data quality report -> %s (%d tickers, %d flagged returns)", path, len(rows), n_flags
    )
    return path
