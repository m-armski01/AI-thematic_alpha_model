"""CLI entrypoint.

Layer 0 behaviour: load+validate the config, read the universe, download the DoD ticker (NVDA),
cache it to Parquet, and print its date range + row count with timing. Re-running hits the cache
and is measurably faster.

    python -m thematic_alpha.run --config configs/base.yaml [--refresh] [--layer 0]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from thematic_alpha.config import Config
from thematic_alpha.data.prices import load_ticker

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
    parser.add_argument(
        "--layer", type=int, default=0, help="Build layer to run (only 0 is implemented)."
    )
    return parser.parse_args(argv)


def _universe_tickers(universe_file: Path) -> list[str]:
    df = pd.read_csv(universe_file, comment="#")
    return df["ticker"].astype(str).tolist()


def run_layer0(config: Config, config_dir: Path, refresh: bool) -> int:
    """Download + cache the DoD ticker and print its report. Returns a process exit code."""
    universe_file = (config_dir / config.universe.file).resolve()
    cache_dir = (config_dir / "data" / "cache").resolve()

    tickers = _universe_tickers(universe_file)
    if LAYER0_TICKER not in tickers:
        logging.warning(
            "%s not found in universe %s; using first ticker '%s' instead.",
            LAYER0_TICKER,
            universe_file,
            tickers[0],
        )
    ticker = LAYER0_TICKER if LAYER0_TICKER in tickers else tickers[0]

    start = time.perf_counter()
    df, report = load_ticker(
        ticker=ticker,
        start=config.run.start_date,
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


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    config = Config.from_yaml(args.config)
    # Paths in the config are relative to the project root (the config file's parent's parent:
    # configs/base.yaml -> project root). Resolve against the config's grandparent.
    config_dir = args.config.resolve().parent.parent

    if args.layer != 0:
        logging.error("Only Layer 0 is implemented so far; got --layer %d.", args.layer)
        return 2

    return run_layer0(config, config_dir, refresh=args.refresh)


if __name__ == "__main__":
    sys.exit(main())
