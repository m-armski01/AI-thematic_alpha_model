"""Position no-trade band (brief v2, decision 3): skip small held->held trades, drift reference."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.golden import assert_golden
from tests.synthetic import make_config
from thematic_alpha.backtest.engine import run_backtest

CFG = make_config()
BT = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
ZERO_COST = CFG.costs.model_copy(update={"bps_per_side": 0.0, "slippage_bps": 0.0, "flat_fee": 0.0})
IDX = pd.bdate_range("2024-01-01", periods=8)
COLS = ["A", "B"]
BAND = 0.02


def _targets(rows: dict) -> pd.DataFrame:
    return pd.DataFrame({IDX[i]: v for i, v in rows.items()}, index=COLS, dtype=float).T


def _run(close: pd.DataFrame, tw: pd.DataFrame, band: float):
    return run_backtest(close, tw, BT, ZERO_COST, position_band=band)


def _flat() -> pd.DataFrame:
    return pd.DataFrame(100.0, index=IDX, columns=COLS)


def _drift_a(target_weight: float, drifted_weight: float, other: float = 0.2) -> pd.DataFrame:
    """Flat prices except A, which is repriced on day 3 so its weight drifts to ``drifted``."""
    close = _flat()
    k = drifted_weight * (1 - target_weight) / (target_weight * (1 - drifted_weight))
    close.loc[IDX[3] :, "A"] = 100.0 * k
    return close


def test_small_change_is_skipped_and_cash_keeps_the_skipped_buy():
    tw = _targets({0: [0.4, 0.4], 3: [0.41, 0.4]})
    on, off = _run(_flat(), tw, BAND), _run(_flat(), tw, 0.0)
    assert len(on.trades) == 2 and len(off.trades) == 3
    equity = off.trades["equity_pre"].iloc[-1]
    assert on.cash.iloc[-1] - off.cash.iloc[-1] == pytest.approx(0.01 * equity)
    # Nothing is renormalized: B is untouched in both runs.
    assert on.weights_history["B"].iloc[-1] == off.weights_history["B"].iloc[-1]


def test_drift_not_target_is_the_reference_trade_executes_when_drifted_out_of_band():
    # Target unchanged at 20% but the name drifted to 23%: |0.20 - 0.23| >= 2pp -> trade.
    tw = _targets({0: [0.2, 0.2], 3: [0.2, 0.2]})
    res = _run(_drift_a(0.20, 0.23), tw, BAND)
    later = res.trades[res.trades["date"] == IDX[3]]
    assert later["ticker"].tolist() == ["A"] and later["side"].iloc[0] == "sell"
    assert later["w_before"].iloc[0] == pytest.approx(0.23)


def test_drift_not_target_is_the_reference_trade_skipped_when_drift_covers_the_move():
    # Target moves 20% -> 22.5% but the name drifted to 22%: |0.225 - 0.22| < 2pp -> skipped.
    tw = _targets({0: [0.2, 0.2], 3: [0.225, 0.2]})
    res = _run(_drift_a(0.20, 0.22), tw, BAND)
    assert (res.trades["date"] == IDX[3]).sum() == 0
    off = _run(_drift_a(0.20, 0.22), tw, 0.0).trades
    assert "A" in off.loc[off["date"] == IDX[3], "ticker"].tolist()  # without the band it trades


def test_exit_below_band_and_entry_always_trade():
    tw = _targets({0: [0.01, 0.5], 3: [0.0, 0.5], 5: [0.01, 0.5]})
    res = _run(_flat(), tw, BAND)
    a = res.trades[res.trades["ticker"] == "A"]
    assert a["date"].tolist() == [IDX[0], IDX[3], IDX[5]]
    assert a["side"].tolist() == ["buy", "sell", "buy"]
    assert res.weights_history.loc[IDX[4], "A"] == 0.0


def test_band_only_applies_to_strategy_runs():
    from tests.golden import golden_run

    _, _, _, results = golden_run(turnover={"position_band": 0.05})
    _, _, _, base = golden_run()
    for name in ["sp500", "equal_weight_bh", "naive_momentum"]:
        pd.testing.assert_frame_equal(results[name].trades, base[name].trades)
    assert len(results["strategy"].trades) < len(base["strategy"].trades)


def test_band_zero_is_golden():
    assert_golden(turnover={"position_band": 0.0})
