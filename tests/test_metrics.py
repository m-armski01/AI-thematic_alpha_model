"""SPEC §9 test_metrics: Sharpe, max drawdown and VaR against hand-computed values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.backtest.engine import BacktestResult
from thematic_alpha.risk import drawdown as dd
from thematic_alpha.risk import metrics as m

IDX = pd.bdate_range("2024-01-01", periods=6)
EQUITY = pd.Series([100.0, 110.0, 99.0, 108.9, 120.0, 114.0], index=IDX)
RETURNS = pd.Series([0.0, 0.10, -0.10, 0.10, 120 / 108.9 - 1, -0.05], index=IDX)


def _result(equity=EQUITY, returns=RETURNS) -> BacktestResult:
    exec_dates = pd.DatetimeIndex([IDX[0], IDX[2], IDX[4]])
    return BacktestResult(
        equity_curve=equity,
        daily_returns=returns,
        weights_history=pd.DataFrame(1.0, index=IDX, columns=["A"]),
        trades=pd.DataFrame(),
        turnover_series=pd.Series([1.0, 0.5, 0.5], index=exec_dates),
        costs_paid=pd.Series([1.0, 0.5, 0.5], index=exec_dates),
        cash=pd.Series(0.0, index=IDX),
        initial_capital=100.0,
        execution_dates=exec_dates,
    )


def test_underwater_and_episodes():
    uw = dd.underwater(EQUITY)
    assert uw.tolist() == pytest.approx([0, 0, -0.10, -0.01, 0, -0.05])
    eps = dd.drawdown_episodes(EQUITY)
    assert len(eps) == 2
    worst = eps.iloc[0]
    assert worst["depth"] == pytest.approx(-0.10)
    assert worst["peak"] == IDX[1] and worst["trough"] == IDX[2] and worst["recovery"] == IDX[4]
    assert worst["duration_days"] == (IDX[4] - IDX[1]).days
    assert pd.isna(eps.iloc[1]["recovery"])  # still underwater at the end


def test_max_drawdown_and_table():
    mdd = dd.max_drawdown(EQUITY)
    assert mdd["depth"] == pytest.approx(-0.10) and mdd["trough"] == IDX[2]
    assert len(dd.drawdown_table(EQUITY, top=1)) == 1
    assert dd.max_drawdown(pd.Series([1.0, 2.0, 3.0], index=IDX[:3]))["depth"] == 0.0


def test_sharpe_by_hand():
    r = RETURNS
    rf = pd.Series(0.0, index=IDX)
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert m.sharpe(r - rf) == pytest.approx(expected)
    # A constant risk-free rate lowers the Sharpe by rf/std * sqrt(252).
    rf2 = pd.Series(0.001, index=IDX)
    assert m.sharpe(r - rf2) == pytest.approx((r.mean() - 0.001) / r.std(ddof=1) * np.sqrt(252))


def test_var_and_cvar_by_hand():
    r = RETURNS
    assert m.historical_var(r, 0.95) == pytest.approx(-np.quantile(r, 0.05))
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.05)
    assert m.parametric_var(r, 0.95) == pytest.approx(-(r.mean() + z * r.std(ddof=1)))
    # CVaR95: mean of returns at or below the 5% quantile, as a positive loss.
    thr = np.quantile(r, 0.05)
    assert m.cvar(r, 0.95) == pytest.approx(-r[r <= thr].mean())


def test_period_returns_hit_rate_and_costs():
    res = _result()
    cfg = make_config().risk
    out = m.compute_metrics(res, pd.Series(0.0, index=IDX), pd.Series(0.0, index=IDX), cfg)
    # Periods: IDX0->IDX2 (100 -> 99: loss), IDX2->IDX4 (99 -> 120: win).
    assert out["n_periods"] == 2 and out["hit_rate"] == 0.5
    assert out["avg_win"] == pytest.approx(120 / 99 - 1) and out["avg_loss"] == pytest.approx(-0.01)
    assert out["total_return"] == pytest.approx(0.14)
    assert out["max_drawdown"] == pytest.approx(-0.10)
    assert out["total_costs"] == 2.0
    assert out["costs_pct_final_equity"] == pytest.approx(2.0 / 114.0)
    assert out["ann_turnover"] == pytest.approx(2.0 / (6 / 252))
    assert out["cagr"] == pytest.approx(1.14 ** (252 / 6) - 1)
    assert "var_hist_95" in out and "var_param_99" in out and "cvar_95" in out


def test_alpha_beta_recover_known_values():
    idx = pd.bdate_range("2020", periods=500)
    rng = np.random.default_rng(0)
    mkt = pd.Series(rng.normal(0.0004, 0.01, 500), idx)
    strat = 0.0002 + 1.3 * mkt
    alpha, beta = m.ols_alpha_beta(strat, mkt)
    assert beta == pytest.approx(1.3, abs=1e-9)
    assert alpha == pytest.approx(0.0002 * 252, abs=1e-6)
    rb = m.rolling_beta(strat, mkt, 60)
    assert rb.dropna().iloc[-1] == pytest.approx(1.3, abs=1e-9)


def test_fx_contribution_zero_when_identical():
    res = _result()
    out = m.fx_contribution(res, res)
    assert out["fx_contribution_total"] == 0.0 and out["fx_contribution_cagr"] == 0.0


def test_metrics_annualize_on_the_market_calendar():
    """A second exchange's extra days must not inflate the year count or dilute returns."""
    from thematic_alpha.backtest.engine import run_backtest

    cfg = make_config()
    bt = cfg.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    zero = cfg.costs.model_copy(update={"bps_per_side": 0.0, "slippage_bps": 0.0, "flat_fee": 0.0})
    nyse = pd.bdate_range("2024-01-01", periods=504)
    extra = nyse[nyse.weekday == 4][::5] + pd.Timedelta(days=1)  # Saturdays: "KRX-only" days
    master = nyse.union(extra)
    close = pd.DataFrame({"A": 100 * (1.001 ** np.arange(len(nyse)))}, index=nyse)
    close = close.reindex(master).ffill()
    tw = pd.DataFrame({"A": [1.0]}, index=[nyse[0]])
    on_master = run_backtest(close, tw, bt, zero, sessions=master)
    on_market = run_backtest(close, tw, bt, zero, sessions=nyse)
    m_master = m.compute_metrics(
        on_master, pd.Series(0.0, index=master), pd.Series(0.0, index=master), cfg.risk
    )
    m_market = m.compute_metrics(
        on_market, pd.Series(0.0, index=nyse), pd.Series(0.0, index=nyse), cfg.risk
    )
    assert m_market["n_days"] == len(nyse) and m_master["n_days"] == len(master)
    assert m_market["cagr"] == pytest.approx(1.001 ** (503 / 2) - 1, rel=1e-9)  # 503 steps, 2y
    assert m_master["cagr"] < m_market["cagr"]  # the master-calendar count understates it
    assert on_market.final_equity == on_master.final_equity  # the engine itself is unchanged
