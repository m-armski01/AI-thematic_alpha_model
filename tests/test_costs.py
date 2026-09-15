"""SPEC §9 test_costs: turnover x cost rate equals the deducted amount; zero turnover, zero cost."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.backtest import costs as c
from thematic_alpha.backtest.engine import run_backtest


def test_cost_models():
    cfg = make_config().costs  # bps 5, flat 1, slippage 3
    assert c.transaction_cost(10_000, 3, cfg) == pytest.approx(10_000 * 8 / 1e4)
    flat = cfg.model_copy(update={"model": "flat_fee"})
    assert c.transaction_cost(10_000, 3, flat) == pytest.approx(10_000 * 3 / 1e4 + 3 * 1.0)
    both = cfg.model_copy(update={"model": "both"})
    assert c.transaction_cost(10_000, 3, both) == pytest.approx(10_000 * 8 / 1e4 + 3.0)
    assert c.transaction_cost(0.0, 0, both) == 0.0


@pytest.fixture
def two_assets():
    idx = pd.bdate_range("2024-01-01", periods=10)
    px = pd.DataFrame({"A": 100.0, "B": 50.0}, index=idx)  # flat prices isolate the cost math
    return idx, px


def test_deducted_equals_turnover_times_rate(two_assets):
    idx, px = two_assets
    cfg = make_config()
    bt = cfg.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [0.6, 0.2], "B": [0.4, 0.8]}, index=[idx[0], idx[5]])
    res = run_backtest(px, tw, bt, cfg.costs)
    rate = c.cost_rate(cfg.costs)
    # Day 0: buy 10,000 notional (minus the cost that the buy is scaled to afford).
    cost0 = res.costs_paid.iloc[0]
    traded0 = res.turnover_series.iloc[0] * cfg.backtest.initial_capital
    assert cost0 == pytest.approx(traded0 * rate)
    # Day 5: rotate 40% -> sells 0.4 x equity, buys 0.4 x equity less the cost (paid from the
    # sale proceeds, since there is no spare cash). Cost = traded notional x rate, exactly.
    eq_before = res.equity_curve.iloc[4]
    traded5 = res.turnover_series.iloc[1] * eq_before
    assert 0.79 * eq_before < traded5 <= 0.8 * eq_before
    assert res.costs_paid.iloc[1] == pytest.approx(traded5 * rate)
    assert res.equity_curve.iloc[5] == pytest.approx(eq_before - res.costs_paid.iloc[1])
    assert res.cash.iloc[5] == pytest.approx(0.0, abs=1e-6)  # buys sized to spend exactly


def test_zero_turnover_zero_cost(two_assets):
    idx, px = two_assets
    cfg = make_config()
    bt = cfg.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [0.5, 0.5], "B": [0.5, 0.5]}, index=[idx[0], idx[5]])
    res = run_backtest(px, tw, bt, cfg.costs)
    assert res.turnover_series.iloc[1] == 0.0
    assert res.costs_paid.iloc[1] == 0.0
    assert res.total_costs == pytest.approx(res.costs_paid.iloc[0])
