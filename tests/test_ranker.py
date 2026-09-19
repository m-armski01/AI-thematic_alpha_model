"""Ranker: z-scores, top-N selection, each weighting scheme, empty cross-sections."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.strategy import ranker

IDX = pd.bdate_range("2024-01-01", periods=2)
COLS = list("ABCDEF")


def _wide(mom_rows, vol_rows=None):
    mom = pd.DataFrame(mom_rows, index=IDX, columns=COLS, dtype=float)
    vol = pd.DataFrame(vol_rows if vol_rows is not None else 0.2, index=IDX, columns=COLS)
    return {"mom_63": mom, "vol_21": vol.astype(float)}


ALL = pd.DataFrame(True, index=IDX, columns=COLS)
# The Layer 1 weighting, pinned explicitly: the YAML config carries the chosen value (equal).
TIERS = make_config(ranker={"weighting": "conviction_tier"}).ranker


def test_zscore_rows_over_eligible_only():
    wide = _wide([[1, 2, 3, 4, 5, 100], [1, 1, 1, 1, 1, 1]])
    elig = ALL.copy()
    elig.loc[IDX[0], "F"] = False
    z = ranker.zscore_rows(wide["mom_63"], elig)
    assert np.isnan(z.loc[IDX[0], "F"])
    assert z.loc[IDX[0], ["A", "B", "C", "D", "E"]].mean() == pytest.approx(0.0)
    assert z.loc[IDX[1]].tolist() == [0.0] * 6  # zero dispersion -> all zero, not NaN


def test_conviction_tiers_in_rank_order():
    cfg = TIERS  # top_n=5, tiers .30 .25 .20 .15 .10
    wide = _wide([[6, 5, 4, 3, 2, 1], [1, 2, 3, 4, 5, 6]])
    w = ranker.rank(wide, ALL, cfg)
    assert w.loc[IDX[0]].tolist() == pytest.approx([0.30, 0.25, 0.20, 0.15, 0.10, 0.0])
    assert w.loc[IDX[1]].tolist() == pytest.approx([0.0, 0.10, 0.15, 0.20, 0.25, 0.30])


def test_tiers_renormalize_when_fewer_survivors():
    cfg = TIERS
    wide = _wide([[3, 2, 1, 0, 0, 0]] * 2)
    elig = ALL.copy()
    elig[["D", "E", "F"]] = False
    w = ranker.rank(wide, elig, cfg)
    total = 0.30 + 0.25 + 0.20
    assert w.loc[IDX[0]].tolist() == pytest.approx(
        [0.30 / total, 0.25 / total, 0.20 / total, 0, 0, 0]
    )
    assert w.sum(axis=1).tolist() == pytest.approx([1.0, 1.0])


def test_equal_and_inverse_vol_weighting():
    cfg = make_config().ranker.model_copy(update={"top_n": 2, "weighting": "equal"})
    wide = _wide([[5, 4, 3, 2, 1, 0]] * 2, vol_rows=[[0.1, 0.3, 1, 1, 1, 1]] * 2)
    w = ranker.rank(wide, ALL, cfg)
    assert w.loc[IDX[0]].tolist() == pytest.approx([0.5, 0.5, 0, 0, 0, 0])
    cfg = cfg.model_copy(update={"weighting": "inverse_vol"})
    w = ranker.rank(wide, ALL, cfg)
    assert w.loc[IDX[0], "A"] == pytest.approx(0.75) and w.loc[IDX[0], "B"] == pytest.approx(0.25)


def test_equal_weight_method_holds_all_eligible():
    cfg = make_config().ranker.model_copy(update={"method": "equal_weight"})
    elig = ALL.copy()
    elig.loc[IDX[0], ["E", "F"]] = False
    w = ranker.rank(_wide([[0] * 6] * 2), elig, cfg)
    assert w.loc[IDX[0]].tolist() == pytest.approx([0.25] * 4 + [0, 0])
    assert w.loc[IDX[1]].tolist() == pytest.approx([1 / 6] * 6)


def test_no_eligible_names_means_cash():
    cfg = make_config().ranker
    w = ranker.rank(_wide([[1] * 6] * 2), ~ALL, cfg)
    assert (w == 0).all().all()


def test_naive_momentum_is_equal_weight_top_n():
    wide = _wide([[6, 5, 4, 3, 2, 1]] * 2)
    w = ranker.naive_momentum(wide, ALL, top_n=3)
    assert w.loc[IDX[0]].tolist() == pytest.approx([1 / 3] * 3 + [0] * 3)


# --- softmax weighting (brief v2, decision 1) ---------------------------------------------


def _softmax_cfg(tau: float, top_n: int = 5):
    return make_config().ranker.model_copy(
        update={"weighting": "softmax", "softmax_temperature": tau, "top_n": top_n}
    )


def test_softmax_weights_sum_to_one_and_are_monotone_in_z():
    wide = _wide([[6, 5, 4, 3, 2, 1], [1, 2, 3, 4, 5, 6]])
    w = ranker.rank(wide, ALL, _softmax_cfg(1.0))
    assert w.sum(axis=1).tolist() == pytest.approx([1.0, 1.0])
    row = w.loc[IDX[0]]
    assert row["F"] == 0.0  # rank 6 not selected
    assert row["A"] > row["B"] > row["C"] > row["D"] > row["E"] > 0
    assert w.loc[IDX[1]].tolist()[::-1] == pytest.approx(row.tolist())


def test_softmax_all_negative_z_is_finite_and_shift_invariant():
    z = np.array([-1.0, -2.0, -3.0, -4.0, -5.0, -6.0])
    wide = _wide([z, z + 100.0])
    # Every eligible name shares the mean/std after a shift, so z is identical on both rows...
    w = ranker.rank(wide, ALL, _softmax_cfg(0.7))
    assert np.isfinite(w.to_numpy()).all() and (w >= 0).all().all()
    assert w.loc[IDX[0]].tolist() == pytest.approx(w.loc[IDX[1]].tolist())
    # ...and the softmax itself is shift-invariant in its input.
    sel = pd.DataFrame(True, index=IDX, columns=COLS)
    score = pd.DataFrame([z, z], index=IDX, columns=COLS)
    a = ranker.softmax_rows(score, sel, 0.7)
    b = ranker.softmax_rows(score - 37.0, sel, 0.7)
    a, b = a.div(a.sum(axis=1), axis=0), b.div(b.sum(axis=1), axis=0)
    pd.testing.assert_frame_equal(a, b)


def test_softmax_limits_equal_weight_and_winner_take_all():
    wide = _wide([[6, 5, 4, 3, 2, 1]] * 2)
    huge = ranker.rank(wide, ALL, _softmax_cfg(1e6)).loc[IDX[0]]
    assert huge.tolist() == pytest.approx([0.2] * 5 + [0.0], abs=1e-6)
    tiny = ranker.rank(wide, ALL, _softmax_cfg(1e-3)).loc[IDX[0]]
    assert tiny["A"] == pytest.approx(1.0) and tiny["B"] < 1e-9


def test_softmax_config_rejects_nonpositive_temperature():
    with pytest.raises(ValueError):
        make_config(ranker={"weighting": "softmax", "softmax_temperature": 0.0})


def test_ranker_reads_the_configured_momentum_signal():
    wide = _wide([[1, 2, 3, 4, 5, 6]] * 2)
    wide["mom_126"] = -wide["mom_63"]  # opposite ordering
    cfg = make_config().ranker.model_copy(update={"weighting": "equal", "top_n": 2})
    top_63 = ranker.rank(wide, ALL, cfg).iloc[0]
    top_126 = ranker.rank(wide, ALL, cfg.model_copy(update={"momentum_signal": "mom_126"})).iloc[0]
    assert set(top_63[top_63 > 0].index) == {"E", "F"}
    assert set(top_126[top_126 > 0].index) == {"A", "B"}
    nm = ranker.naive_momentum(wide, ALL, top_n=2, signal="mom_126").iloc[0]
    assert set(nm[nm > 0].index) == {"A", "B"}
