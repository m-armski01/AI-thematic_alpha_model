"""Macro gate action block_increases (brief v2, decision 4a)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.golden import assert_golden, golden_run
from tests.synthetic import WIDE_SEGMENTS, make_config
from thematic_alpha.strategy.compose import compose_target_weights
from thematic_alpha.strategy.macro_gate import applied_gate, gate_factors

DATES = pd.bdate_range("2024-01-05", periods=4, freq="W-FRI")
COLS = ["A", "B", "C"]
SIZING = make_config().sizing.model_copy(update={"max_position_weight": 1.0})
ONE = pd.Series(1.0, DATES)


def _rw(rows):
    return pd.DataFrame(rows, index=DATES, columns=COLS, dtype=float)


def _risk_off(flags):
    return pd.Series(flags, index=DATES)


def test_risk_off_caps_non_exempt_names_at_previous_target_and_leaves_cash():
    rw = _rw([[0.5, 0.5, 0.0], [0.7, 0.3, 0.0], [0.4, 0.3, 0.3], [0.4, 0.3, 0.3]])
    res = compose_target_weights(
        rw, ONE, DATES, SIZING, risk_off=_risk_off([False, True, True, False])
    )
    w = res.target_weights
    assert w.iloc[1].tolist() == pytest.approx([0.5, 0.3, 0.0])  # A capped, B's decrease passes
    assert w.iloc[1].sum() == pytest.approx(0.8)  # blocked weight is cash, not redistributed
    assert w.iloc[2].tolist() == pytest.approx([0.4, 0.3, 0.0])  # C's entry blocked
    assert w.iloc[3].tolist() == pytest.approx([0.4, 0.3, 0.3])  # risk-on: ranker passes through
    assert res.gate_blocked == 2 and res.risk_off.tolist() == [False, True, True, False]
    assert (res.exposure == 1.0).all()


def test_exits_pass_while_risk_off():
    rw = _rw([[0.5, 0.5, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    res = compose_target_weights(rw, ONE, DATES, SIZING, risk_off=_risk_off([False, True] * 2))
    assert res.target_weights.iloc[1].tolist() == pytest.approx([0.5, 0.0, 0.0])


def test_exempt_segment_name_can_increase_and_enter_while_risk_off():
    rw = _rw([[0.5, 0.5, 0.0], [0.3, 0.3, 0.4], [0.2, 0.2, 0.6], [0.2, 0.2, 0.6]])
    res = compose_target_weights(
        rw, ONE, DATES, SIZING, risk_off=_risk_off([False, True, True, True]), exempt=["C"]
    )
    w = res.target_weights
    assert w.iloc[1].tolist() == pytest.approx([0.3, 0.3, 0.4])  # C enters while risk-off
    assert w.iloc[2].tolist() == pytest.approx([0.2, 0.2, 0.6])  # ...and increases


def test_block_mode_is_a_pure_history_function_and_sums_below_one():
    _, _, strategy, _ = golden_run(
        macro_gate={"action": "block_increases", "block_exempt_segments": ["defensive"]}
    )
    w = strategy.target_weights
    assert (w.sum(axis=1) <= 1.0 + 1e-12).all()
    ro = strategy.applied.risk_off
    assert ro.any() and not ro.all()
    exempt = {t for t, seg in WIDE_SEGMENTS.items() if seg == "defensive"}
    prev = w.shift(1).fillna(0.0)
    for t in w.columns:
        if t in exempt:
            continue
        assert (w.loc[ro, t] <= prev.loc[ro, t] + 1e-12).all(), t
    # The scale-mode exposure is not applied in block mode.
    assert (strategy.composed.exposure == 1.0).all()


def test_risk_off_is_any_subgate_engaged_and_fails_open_on_nan():
    cfg = make_config().macro_gate.model_copy(
        update={"action": "block_increases", "evaluation": "weekly"}
    )
    idx = pd.bdate_range("2024-01-01", periods=4)
    feats = pd.DataFrame(
        {
            "vix_level": [15.0, 30.0, np.nan, 15.0],
            "dgs10_chg_21d": [0.0, 0.0, 0.0, 0.5],
            "wti_chg_21d": [0.0, 0.0, np.nan, 0.0],
        },
        index=idx,
    )
    g = gate_factors(feats, cfg)
    assert g["risk_off"].tolist() == [False, True, False, True]
    state = applied_gate(g, idx, cfg)
    assert state.risk_off.tolist() == [False, True, False, True]
    assert (state.exposure == 1.0).all() and state.action == "block_increases"
    scale = applied_gate(g, idx, cfg.model_copy(update={"action": "scale"}))
    assert (~scale.risk_off).all() and scale.exposure.tolist() == [1.0, 0.5, 1.0, 0.7]


def test_scale_action_is_golden():
    assert_golden(macro_gate={"action": "scale", "block_exempt_segments": ["defensive"]})
