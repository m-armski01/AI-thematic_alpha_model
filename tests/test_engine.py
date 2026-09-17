"""SPEC §9 test_engine: buy-and-hold reproduction, weights <= 1, cash >= 0, drift, lag, NaN."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.backtest import benchmarks
from thematic_alpha.backtest.engine import execution_dates, run_backtest

CFG = make_config()
ZERO_COST = CFG.costs.model_copy(update={"bps_per_side": 0.0, "slippage_bps": 0.0, "flat_fee": 0.0})


@pytest.fixture
def market():
    idx = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(3)
    close = pd.DataFrame(
        {
            "A": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))),
            "B": 50 * np.exp(np.cumsum(rng.normal(0, 0.03, 60))),
        },
        index=idx,
    )
    open_ = close * (1 + rng.normal(0, 0.005, close.shape))
    return idx, close, open_


def test_single_asset_full_weight_reproduces_buy_and_hold(market):
    idx, close, _ = market
    bt = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [1.0], "B": [0.0]}, index=[idx[0]])
    res = run_backtest(close, tw, bt, ZERO_COST)
    expected = close["A"] / close["A"].iloc[0] * bt.initial_capital
    pd.testing.assert_series_equal(res.equity_curve, expected, check_names=False, rtol=1e-12)
    assert res.total_costs == 0.0 and (res.cash.abs() < 1e-9).all()


def test_weights_never_exceed_one_and_cash_never_negative(market):
    idx, close, open_ = market
    rng = np.random.default_rng(7)
    sig = idx[::5]
    raw = rng.uniform(0, 1, (len(sig), 2))
    raw = raw / raw.sum(axis=1, keepdims=True) * rng.uniform(0.5, 1.0, (len(sig), 1))
    tw = pd.DataFrame(raw, index=sig, columns=["A", "B"])
    res = run_backtest(close, tw, CFG.backtest, CFG.costs, prices_open=open_)
    assert (res.weights_history.sum(axis=1) <= 1.0 + 1e-9).all()
    assert (res.weights_history >= 0).all().all()
    assert (res.cash >= 0).all()
    # Equity identity holds every day.
    held = res.equity_curve - res.cash
    assert (held >= -1e-9).all()


def test_weights_drift_between_rebalances(market):
    idx, close, _ = market
    bt = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [0.5], "B": [0.5]}, index=[idx[0]])
    res = run_backtest(close, tw, bt, ZERO_COST)
    w = res.weights_history
    assert w.iloc[0].tolist() == pytest.approx([0.5, 0.5])
    assert w["A"].nunique() > 1  # drifts...
    assert res.trades["date"].nunique() == 1  # ...without any re-normalizing trade
    shares_a = res.trades.loc[res.trades.ticker == "A", "shares"].sum()
    assert res.equity_curve.iloc[-1] == pytest.approx(
        shares_a * close["A"].iloc[-1]
        + res.trades.loc[res.trades.ticker == "B", "shares"].sum() * close["B"].iloc[-1]
    )


def test_execution_lag_and_price(market):
    idx, close, open_ = market
    bt = CFG.backtest.model_copy(update={"execution_lag_days": 1, "execution_price": "open"})
    tw = pd.DataFrame({"A": [1.0], "B": [0.0]}, index=[idx[3]])
    res = run_backtest(close, tw, bt, ZERO_COST, prices_open=open_)
    trade = res.trades.iloc[0]
    assert trade["date"] == idx[4]  # signal t -> executed t+1
    assert trade["price"] == open_.loc[idx[4], "A"]  # ...at the open
    assert (res.weights_history.loc[: idx[3]] == 0).all().all()  # nothing held before
    # On the execution day equity earns open -> close on the new position.
    assert res.equity_curve.loc[idx[4]] == pytest.approx(
        bt.initial_capital * close.loc[idx[4], "A"] / open_.loc[idx[4], "A"]
    )


def test_execution_dates_mapping_and_tail_drop():
    sessions = pd.bdate_range("2024-01-01", periods=5)
    sig = pd.DatetimeIndex([sessions[0], sessions[4]])
    m = execution_dates(sig, sessions, lag=1)
    assert m.tolist() == [sessions[1]]  # the last signal has no t+1 session -> dropped


def test_nan_price_target_left_in_cash(market, caplog):
    idx, close, _ = market
    close = close.copy()
    close.loc[: idx[9], "B"] = np.nan  # B not yet listed
    bt = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [0.5], "B": [0.5]}, index=[idx[0]])
    with caplog.at_level("WARNING"):
        res = run_backtest(close, tw, bt, ZERO_COST)
    assert res.cash.iloc[0] == pytest.approx(0.5 * bt.initial_capital)
    assert res.weights_history.loc[idx[0], "B"] == 0.0
    assert "untradeable" in caplog.text


def test_invalid_targets_rejected(market):
    idx, close, _ = market
    with pytest.raises(ValueError):
        run_backtest(
            close, pd.DataFrame({"A": [0.7], "B": [0.5]}, index=[idx[0]]), CFG.backtest, CFG.costs
        )


def test_buy_and_hold_targets_rebalance_only_on_set_change():
    idx = pd.bdate_range("2024-01-05", periods=4, freq="W-FRI")
    elig = pd.DataFrame(
        [[True, False], [True, False], [True, True], [True, True]], index=idx, columns=["A", "B"]
    )
    tw = benchmarks.buy_and_hold_targets(elig, idx)
    assert tw.index.tolist() == [idx[0], idx[2]]
    assert tw.loc[idx[0]].tolist() == [1.0, 0.0] and tw.loc[idx[2]].tolist() == [0.5, 0.5]


def test_idle_cash_compounds_at_the_given_rate(market):
    idx, close, open_ = market
    tw = pd.DataFrame({"A": [0.0], "B": [0.0]}, index=[idx[0]])  # 100% cash throughout
    rate = pd.Series(0.0004, index=idx)
    res = run_backtest(close, tw, CFG.backtest, CFG.costs, prices_open=open_, cash_rate=rate)
    # The book starts on the first execution date (signal + 1 session) and accrues every session.
    expected = CFG.backtest.initial_capital * np.cumprod(1.0 + rate.reindex(res.equity_curve.index))
    np.testing.assert_allclose(res.equity_curve.to_numpy(), expected.to_numpy(), rtol=1e-12)
    np.testing.assert_allclose(res.cash.to_numpy(), expected.to_numpy(), rtol=1e-12)
    flat = run_backtest(close, tw, CFG.backtest, CFG.costs, prices_open=open_)
    assert (flat.equity_curve == CFG.backtest.initial_capital).all()


def test_cash_rate_is_aligned_by_date_and_missing_dates_accrue_nothing(market):
    idx, close, open_ = market
    tw = pd.DataFrame({"A": [0.0], "B": [0.0]}, index=[idx[0]])
    # Rate only on the first half of the window, indexed on a superset of dates.
    rate = pd.Series(0.001, index=idx[:30].union(pd.bdate_range("2020-01-01", periods=5)))
    res = run_backtest(close, tw, CFG.backtest, CFG.costs, prices_open=open_, cash_rate=rate)
    n_accruing = int(res.equity_curve.index.isin(idx[:30]).sum())
    final = CFG.backtest.initial_capital * 1.001**n_accruing
    assert abs(res.equity_curve.loc[idx[29]] - final) < 1e-9
    assert (res.equity_curve.loc[idx[29] :] == res.equity_curve.loc[idx[29]]).all()


def test_cash_accrual_reaches_the_invested_book_only_through_cash(market):
    idx, close, open_ = market
    bt = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
    tw = pd.DataFrame({"A": [1.0], "B": [0.0]}, index=[idx[0]])  # fully invested from day 0
    rate = pd.Series(0.01, index=idx[1:])  # no accrual before the opening trade
    with_rf = run_backtest(close, tw, bt, ZERO_COST, cash_rate=rate)
    without = run_backtest(close, tw, bt, ZERO_COST)
    pd.testing.assert_series_equal(with_rf.equity_curve, without.equity_curve)
