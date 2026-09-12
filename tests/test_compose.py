"""Compose: mask blocks increases only, gate scales, limits cap, weights never exceed 1."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.strategy.compose import compose_target_weights
from thematic_alpha.strategy.event_mask import EventMask
from thematic_alpha.strategy.sizing import apply_limits

DATES = pd.bdate_range("2024-01-05", periods=3, freq="W-FRI")
COLS = ["A", "B", "C"]
SIZING = make_config().sizing  # max 0.35, cash floor 0


def _rw(rows):
    return pd.DataFrame(rows, index=DATES, columns=COLS, dtype=float)


def _mask(rows):
    return EventMask(blocked=pd.DataFrame(rows, index=DATES, columns=COLS, dtype=bool))


def test_no_mask_no_gate_passes_through_with_cap():
    rw = _rw([[0.5, 0.3, 0.2]] * 3)
    res = compose_target_weights(rw, pd.Series(1.0, DATES), DATES, SIZING)
    assert res.target_weights.iloc[0].tolist() == pytest.approx([0.35, 0.3, 0.2])
    assert res.entries_blocked == 0


def test_gate_scales_and_cash_remains():
    rw = _rw([[0.3, 0.3, 0.3]] * 3)
    exp = pd.Series([1.0, 0.5, 0.3], DATES)
    res = compose_target_weights(rw, exp, DATES, SIZING)
    assert res.target_weights.sum(axis=1).tolist() == pytest.approx([0.9, 0.45, 0.27])


def test_mask_blocks_increase_but_allows_hold_and_decrease():
    rw = _rw([[0.5, 0.5, 0.0], [0.2, 0.8, 0.0], [0.2, 0.8, 0.0]])
    mask = _mask([[False] * 3, [False, True, False], [False, True, False]])
    cfg = SIZING.model_copy(update={"max_position_weight": 1.0})
    res = compose_target_weights(rw, pd.Series(1.0, DATES), DATES, cfg, mask)
    pre = res.pre_gate_weights
    # Date 2: B wants 0.5 -> 0.8 but is blocked; held at 0.5, freed 0.3 goes to A.
    assert pre.iloc[1].tolist() == pytest.approx([0.5, 0.5, 0.0])
    # Date 3: B at 0.5 wants 0.8 again -> still blocked (compared with previous share).
    assert pre.iloc[2].tolist() == pytest.approx([0.5, 0.5, 0.0])
    assert res.entries_blocked == 2
    assert res.masked_ticker_dates == 2


def test_mask_never_blocks_a_decrease():
    rw = _rw([[0.0, 1.0, 0.0], [0.5, 0.5, 0.0], [0.5, 0.5, 0.0]])
    mask = _mask([[False] * 3, [False, True, False], [False] * 3])
    cfg = SIZING.model_copy(update={"max_position_weight": 1.0})
    res = compose_target_weights(rw, pd.Series(1.0, DATES), DATES, cfg, mask)
    assert res.pre_gate_weights.iloc[1].tolist() == pytest.approx([0.5, 0.5, 0.0])
    assert res.entries_blocked == 0


def test_weights_never_exceed_one_and_never_negative():
    rw = _rw([[0.9, 0.9, 0.9]] * 3)  # a badly normalized input
    res = compose_target_weights(rw, pd.Series(1.0, DATES), DATES, SIZING)
    assert (res.target_weights.sum(axis=1) <= 1.0 + 1e-12).all()
    assert (res.target_weights >= 0).all().all()


def test_apply_limits_cap_goes_to_cash_and_floor_scales():
    w = pd.DataFrame([[0.6, 0.4]], columns=["A", "B"])
    out = apply_limits(w, max_position_weight=0.35, cash_floor=0.0)
    assert out.iloc[0].tolist() == pytest.approx([0.35, 0.35])  # excess -> cash, not redistributed
    out = apply_limits(w, max_position_weight=0.5, cash_floor=0.0)
    assert out.iloc[0].tolist() == pytest.approx([0.5, 0.4])
    out = apply_limits(w, max_position_weight=1.0, cash_floor=0.2)
    assert out.iloc[0].tolist() == pytest.approx([0.48, 0.32])
