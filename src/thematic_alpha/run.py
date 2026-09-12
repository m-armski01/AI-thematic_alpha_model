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
