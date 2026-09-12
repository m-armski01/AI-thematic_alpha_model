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


def test_zscore_rows_over_eligible_only():
    wide = _wide([[1, 2, 3, 4, 5, 100], [1, 1, 1, 1, 1, 1]])
    elig = ALL.copy()
    elig.loc[IDX[0], "F"] = False
    z = ranker.zscore_rows(wide["mom_63"], elig)
    assert np.isnan(z.loc[IDX[0], "F"])
    assert z.loc[IDX[0], ["A", "B", "C", "D", "E"]].mean() == pytest.approx(0.0)
    assert z.loc[IDX[1]].tolist() == [0.0] * 6  # zero dispersion -> all zero, not NaN


def test_conviction_tiers_in_rank_order():
    cfg = make_config().ranker  # top_n=5, tiers .30 .25 .20 .15 .10
    wide = _wide([[6, 5, 4, 3, 2, 1], [1, 2, 3, 4, 5, 6]])
    w = ranker.rank(wide, ALL, cfg)
    assert w.loc[IDX[0]].tolist() == pytest.approx([0.30, 0.25, 0.20, 0.15, 0.10, 0.0])
    assert w.loc[IDX[1]].tolist() == pytest.approx([0.0, 0.10, 0.15, 0.20, 0.25, 0.30])


def test_tiers_renormalize_when_fewer_survivors():
    cfg = make_config().ranker
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


def test_ml_method_not_implemented():
    cfg = make_config().ranker.model_copy(update={"method": "ml"})
    with pytest.raises(NotImplementedError):
        ranker.rank(_wide([[1] * 6] * 2), ALL, cfg)


def test_naive_momentum_is_equal_weight_top_n():
    wide = _wide([[6, 5, 4, 3, 2, 1]] * 2)
    w = ranker.naive_momentum(wide, ALL, top_n=3)
    assert w.loc[IDX[0]].tolist() == pytest.approx([1 / 3] * 3 + [0] * 3)
