"""CLI entrypoint.

    python -m thematic_alpha.run --config configs/base.yaml [--refresh] [--layer N]

Layer 0: download + cache NVDA, print its date range and row count (cache hit on rerun).
Layer 1: full data load (universe + benchmarks + FRED), master calendar, data-quality report.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from thematic_alpha.config import Config
from thematic_alpha.data.prices import load_ticker
from thematic_alpha.data.universe import load_universe

# The single ticker exercised by the Layer 0 Definition of Done.
LAYER0_TICKER = "NVDA"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="thematic_alpha.run",
        description="Run the thematic-alpha pipeline for a given build layer.",
    )
    parser.add_argument("--config", required=True, type=Path, help="Path to a YAML config file.")
    parser.add_argument(
        "--refresh", action="store_true", help="Force re-download, ignoring cached data."
    )
    parser.add_argument("--layer", type=int, default=1, help="Build layer to run (0 or 1).")
    return parser.parse_args(argv)


def run_layer0(config: Config, root: Path, refresh: bool) -> int:
    """Download + cache the DoD ticker and print its report. Returns a process exit code."""
    tickers = load_universe(root / config.universe.file).tickers
    cache_dir = root / "data" / "cache"
    if LAYER0_TICKER not in tickers:
        logging.warning("%s not in universe; using first ticker '%s'.", LAYER0_TICKER, tickers[0])
    ticker = LAYER0_TICKER if LAYER0_TICKER in tickers else tickers[0]

    start = time.perf_counter()
    df, report = load_ticker(
        ticker=ticker,
        start=config.data.history_start,
        end=config.run.end_date,
        cache_dir=cache_dir,
        max_cache_age_days=config.data.max_cache_age_days,
        refresh=refresh,
    )
    elapsed = time.perf_counter() - start

    if df.empty:
        logging.error("No data returned for %s. Try re-running with --refresh.", ticker)
        return 1

    source = "cache" if report.from_cache else "download"
    print(
        f"\n[Layer 0] {ticker}: {report.rows} rows | "
        f"{report.first_date.date()} -> {report.last_date.date()} "
        f"| source={source} | {elapsed:.2f}s"
    )
    return 0


def run_layer1(config: Config, root: Path, refresh: bool) -> int:
    from thematic_alpha import pipeline

    t0 = time.perf_counter()
    bundle = pipeline.load_data(config, root, refresh=refresh)
    t_data = time.perf_counter() - t0
    quality_path = pipeline.write_data_quality(bundle, config, root)

    n_cached = sum(r.from_cache for r in bundle.reports)
    print(
        f"\n[Layer 1A] {len(bundle.panel.tickers)} price series "
        f"({n_cached}/{len(bundle.reports)} from cache) | "
        f"{len(bundle.macro_raw.columns)} FRED series | "
        f"master calendar {bundle.master.min().date()} -> {bundle.master.max().date()} "
        f"({len(bundle.master)} sessions) | {t_data:.1f}s"
    )
    print(f"[Layer 1A] data quality report -> {quality_path}")

    t0 = time.perf_counter()
    features = pipeline.build_features(bundle, config)
    t_feat = time.perf_counter() - t0
    feat_path = root / "outputs" / "feature_panel.parquet"
    features.tidy.to_parquet(feat_path)
    last = features.dates[-1]
    print(
        f"[Layer 1B] feature panel {features.tidy.shape[0]} rows x {features.tidy.shape[1]} cols "
        f"| eligible on {last.date()}: {int(features.eligible.loc[last].sum())}"
        f"/{features.eligible.shape[1]} | {t_feat:.1f}s -> {feat_path.name}"
    )

    strategy = pipeline.build_strategy(bundle, features, config, root)
    tw = strategy.target_weights
    tw_path = root / "outputs" / "target_weights.csv"
    tw.round(6).to_csv(tw_path)
    c = strategy.composed
    print(
        f"[Layer 1C] {len(strategy.signal_dates)} signal dates | exposure mean "
        f"{c.exposure.mean():.2f} (min {c.exposure.min():.2f}) | avg invested "
        f"{100 * tw.sum(axis=1).mean():.0f}% | event mask: {c.entries_blocked} entries blocked "
        f"pre-earnings, {len(c.failed_open)} tickers failed open -> {tw_path.name}"
    )

    t0 = time.perf_counter()
    results = pipeline.run_backtests(bundle, features, strategy, config)
    t_bt = time.perf_counter() - t0
    ccy = config.run.base_currency
    for name in [pipeline.STRATEGY, *pipeline.BENCHMARK_ORDER]:
        r = results[name]
        print(
            f"[Layer 1D] {name:<16} {r.equity_curve.index[0].date()} -> "
            f"{r.equity_curve.index[-1].date()} | final {r.final_equity:,.0f} {ccy} "
            f"(x{r.final_equity / r.initial_capital:.2f}) | costs {r.total_costs:,.0f} {ccy} "
            f"| {len(r.trades)} trades"
        )
    print(f"[Layer 1D] 4 backtests + local-currency run in {t_bt:.1f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    config = Config.from_yaml(args.config)
    # Paths in the config are relative to the project root (configs/base.yaml -> project root).
    root = args.config.resolve().parent.parent

    if args.layer == 0:
        return run_layer0(config, root, refresh=args.refresh)
    if args.layer == 1:
        return run_layer1(config, root, refresh=args.refresh)
    logging.error("Layers 0 and 1 are implemented; got --layer %d.", args.layer)
    return 2


if __name__ == "__main__":
    sys.exit(main())
