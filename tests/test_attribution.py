"""Turnover attribution: exact sums, pure-cause cases, gate diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.golden import golden_run
from tests.synthetic import make_config
from thematic_alpha.backtest import attribution as attr
from thematic_alpha.backtest.engine import run_backtest
from thematic_alpha.risk.metrics import compute_metrics

CFG = make_config()
BT = CFG.backtest.model_copy(update={"execution_lag_days": 0, "execution_price": "close"})
ZERO_COST = CFG.costs.model_copy(update={"bps_per_side": 0.0, "slippage_bps": 0.0, "flat_fee": 0.0})
IDX = pd.bdate_range("2024-01-01", periods=12)
COLS = ["A", "B", "C"]


def _frame(rows: dict) -> pd.DataFrame:
    """{date position: [wA, wB, wC]} -> signal-date frame."""
    return pd.DataFrame(
        {IDX[i]: v for i, v in rows.items()}, index=COLS, dtype=float
    ).T.sort_index()


def _attributed(close: pd.DataFrame, w: pd.DataFrame, p=None, q=None) -> pd.DataFrame:
    res = run_backtest(close, w, BT, ZERO_COST)
    p = w if p is None else p
    q = w if q is None else q
    return attr.attribute_trades(res, p, q)


def _pure(rows: pd.DataFrame, cause: str) -> None:
    assert len(rows) > 0
    others = [c for c in attr.CAUSES if c != cause]
    assert rows[cause].to_numpy() == pytest.approx(rows["traded"].to_numpy())
    assert (rows[others].abs() < 1e-12).all().all()


FLAT = pd.DataFrame(100.0, index=IDX, columns=COLS)


def test_entry_and_exit_are_pure_membership():
    w = _frame({0: [0.5, 0.5, 0.0], 3: [0.5, 0.0, 0.5]})
    out = _attributed(FLAT, w)
    assert set(zip(out["date"].dt.day, out["ticker"], strict=True)) == {
        (1, "A"),
        (1, "B"),
        (4, "B"),
        (4, "C"),
    }  # A is held-held at an unchanged target and flat prices: no trade
    _pure(out, "membership")


def test_gate_scale_change_is_pure_gate():
    p = _frame({0: [0.5, 0.5, 0.0], 3: [0.5, 0.5, 0.0], 6: [0.5, 0.5, 0.0]})
    exposure = pd.Series([1.0, 0.5, 1.0], index=p.index)
    q = p.mul(exposure, axis=0)
    out = _attributed(FLAT, q, p, q)
    later = out[out["date"] > IDX[0]]
    assert sorted(later["date"].dt.day.unique()) == [4, 9]
    _pure(later, "gate")
    assert later.loc[later["date"] == IDX[3], "gate"].sum() == pytest.approx(0.5)  # 2 x 0.25


def test_gate_block_and_release_are_pure_gate():
    # The ranker wants A up to 0.7 on date 3, the block holds it at 0.5; the release on date 6
    # lets the pent-up increase through. B's reduction on date 3 is the ranker's (reweight).
    p = _frame({0: [0.5, 0.5, 0.0], 3: [0.7, 0.3, 0.0], 6: [0.7, 0.3, 0.0]})
    q = _frame({0: [0.5, 0.5, 0.0], 3: [0.5, 0.3, 0.0], 6: [0.7, 0.3, 0.0]})
    out = _attributed(FLAT, q, p, q)
    d3 = out[out["date"] == IDX[3]]
    assert d3["ticker"].tolist() == ["B"]
    _pure(d3, "reweight")
    d6 = out[out["date"] == IDX[6]]
    assert d6["ticker"].tolist() == ["A"]
    _pure(d6, "gate")
    assert d6["gate"].iloc[0] == pytest.approx(0.2)


def test_drift_only_is_pure_drift():
    rng = np.random.default_rng(5)
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.03, (len(IDX), 3)), axis=0)),
        index=IDX,
        columns=COLS,
    )
    w = _frame({0: [0.5, 0.5, 0.0], 5: [0.5, 0.5, 0.0]})
    out = _attributed(close, w)
    later = out[out["date"] == IDX[5]]
    assert len(later) == 2
    _pure(later, "drift")


def test_allocation_nets_opposing_components():
    # Held name: target 0.5 -> 0.6 (reweight +0.1) while it drifted up to 0.55 (drift -0.05):
    # delta = +0.05, only reweight matches the sign and takes the whole trade.
    close = FLAT.copy()
    close.loc[IDX[1] :, "A"] = 100 * 0.55 / 0.45  # A: 0.5 -> 0.55 of equity (B flat)
    w = _frame({0: [0.5, 0.5, 0.0], 3: [0.6, 0.4, 0.0]})
    out = _attributed(close, w)
    a = out[(out["date"] == IDX[3]) & (out["ticker"] == "A")].iloc[0]
    assert a["delta"] > 0 and a["drift_raw"] < 0 < a["reweight_raw"]
    assert a["reweight"] == pytest.approx(a["traded"]) and a["drift"] == 0.0


def test_causes_sum_to_turnover_per_trade_and_per_run():
    _, _, strategy, results = golden_run()
    c = strategy.composed
    res = results["strategy"]
    out = attr.attribute_trades(res, c.pre_gate_weights, c.post_gate_weights)
    assert out[attr.CAUSES].sum(axis=1).to_numpy() == pytest.approx(
        out["traded"].to_numpy(), abs=1e-12
    )
    assert (out[attr.CAUSES] >= -1e-15).all().all()
    years = attr.years_of(res)
    by_cause = attr.turnover_by_cause(out, years)
    rf = pd.Series(0.0, index=res.daily_returns.index)
    m = compute_metrics(res, rf, rf, CFG.risk)
    assert by_cause["total"] == pytest.approx(m["ann_turnover"], rel=1e-12)
    assert by_cause[attr.CAUSES].sum() == pytest.approx(by_cause["total"], rel=1e-12)
    assert by_cause["gate"] > 0 and by_cause["membership"] > 0  # the fixture exercises both
    # Benchmarks: p = q = targets, so the gate component is identically zero.
    bh = results["equal_weight_bh"]
    out_bh = attr.attribute_trades(bh, bh.target_weights, bh.target_weights)
    assert out_bh["gate"].abs().sum() == 0.0
    assert attr.turnover_by_cause(out_bh, attr.years_of(bh))["total"] == pytest.approx(
        bh.turnover_series.sum() / attr.years_of(bh)
    )


def test_gate_diagnostics_counts_transitions_and_reversals():
    state = pd.Series([1, 1, 0.5, 1, 1, 0.5, 0.5, 1], index=pd.bdate_range("2024", periods=8))
    d = attr.gate_diagnostics(state, years=2.0)
    assert d.n_transitions == 4 and d.per_year == 2.0
    assert d.reversed_within_1 == 1 and d.reversed_within_2 == 3
    assert attr.gate_diagnostics(pd.Series([1.0, 1.0]), 1.0).n_transitions == 0
