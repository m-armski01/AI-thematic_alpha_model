"""Golden regression helper: run the wide synthetic market and compare with the frozen fixture.

The fixture (``tests/fixtures/golden_*``) was produced by ``scripts/freeze_golden.py`` from the
Layer 1 code. Every later knob has a neutral default that must reproduce it exactly; tests for
those knobs call ``assert_golden`` with the neutral value switched on explicitly.
"""

from __future__ import annotations

import json

import pandas as pd

from tests.conftest import PROJECT_ROOT
from tests.synthetic import Market, make_wide_market, run_pipeline, wide_config

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
TOL = {"rtol": 1e-12, "atol": 1e-12}

_MARKET: Market | None = None


def wide_market() -> Market:
    global _MARKET
    if _MARKET is None:
        _MARKET = make_wide_market()
    return _MARKET


def load_golden() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, dict]:
    targets = pd.read_csv(FIXTURES / "golden_targets.csv", index_col=0, parse_dates=True)
    trades = pd.read_csv(FIXTURES / "golden_trades.csv", parse_dates=["date"])
    turnover = pd.read_csv(FIXTURES / "golden_turnover.csv", index_col=0, parse_dates=True)[
        "turnover"
    ]
    meta = json.loads((FIXTURES / "golden_meta.json").read_text())
    return targets, trades, turnover, meta


def golden_run(**overrides):
    """Run the pipeline with Layer 1 settings plus ``overrides`` on the wide market."""
    return run_pipeline(wide_market(), wide_config(**overrides), FIXTURES)


def assert_golden(**overrides) -> None:
    """Assert that the run with ``overrides`` reproduces the frozen Layer 1 fixture."""
    targets, trades, turnover, meta = load_golden()
    _, _, strategy, results = golden_run(**overrides)
    strat = results["strategy"]
    got_targets = strategy.target_weights
    got_targets.index.name = targets.index.name
    pd.testing.assert_frame_equal(got_targets, targets, check_names=False, **TOL)
    got_trades = strat.trades[trades.columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(got_trades, trades, **TOL)
    got_turnover = strat.turnover_series.rename("turnover")
    got_turnover.index.name = turnover.index.name
    pd.testing.assert_series_equal(got_turnover, turnover, check_names=False, **TOL)
    for name, value in meta["final_equity"].items():
        assert abs(results[name].final_equity - value) < 1e-8 * value, name
