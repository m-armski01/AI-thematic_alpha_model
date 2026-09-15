"""Macro gate: each sub-gate, every combination mode, the floor, disabled, and fail-open."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.strategy.macro_gate import compute_exposure, gate_factors


def _feats(vix, dgs10_chg, wti_chg):
    idx = pd.bdate_range("2024-01-01", periods=len(vix))
    return pd.DataFrame(
        {"vix_level": vix, "dgs10_chg_21d": dgs10_chg, "wti_chg_21d": wti_chg}, index=idx
    )


CFG = make_config().macro_gate  # vix 25/0.5, yield 0.40/0.7, oil 0.20/0.85, floor 0.30


def test_risk_on_is_full_exposure():
    f = gate_factors(_feats([15.0], [0.1], [0.05]), CFG)
    assert f.iloc[0][["vix_factor", "yield_factor", "oil_factor", "exposure"]].tolist() == [1.0] * 4
    assert not f["risk_off"].iloc[0]


def test_each_subgate_fires_independently():
    f = gate_factors(_feats([30.0, 15.0, 15.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.3]), CFG)
    assert f["vix_factor"].tolist() == [0.5, 1.0, 1.0]
    assert f["yield_factor"].tolist() == [1.0, 0.7, 1.0]
    assert f["oil_factor"].tolist() == [1.0, 1.0, 0.85]


def test_threshold_is_strict():
    f = gate_factors(_feats([25.0], [0.40], [0.20]), CFG)
    assert f["exposure"].iloc[0] == 1.0


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("multiplicative", max(0.5 * 0.7 * 0.85, 0.3)),
        ("min", 0.5),
        ("average", (0.5 + 0.7 + 0.85) / 3),
    ],
)
def test_combination_modes(mode, expected):
    cfg = CFG.model_copy(update={"combination": mode})
    e = compute_exposure(_feats([40.0], [1.0], [0.5]), cfg)
    assert e.iloc[0] == pytest.approx(expected)


def test_floor_applies():
    cfg = CFG.model_copy(update={"vix_scale_factor": 0.1, "yield_scale_factor": 0.1})
    e = compute_exposure(_feats([40.0], [1.0], [0.0]), cfg)
    assert e.iloc[0] == cfg.min_exposure


def test_disabled_gate_is_one():
    cfg = CFG.model_copy(update={"enabled": False})
    e = compute_exposure(_feats([80.0], [2.0], [1.0]), cfg)
    assert e.iloc[0] == 1.0


def test_nan_input_fails_open(caplog):
    with caplog.at_level("WARNING"):
        f = gate_factors(_feats([np.nan], [np.nan], [0.5]), CFG)
    assert f["vix_factor"].iloc[0] == 1.0 and f["yield_factor"].iloc[0] == 1.0
    assert f["oil_factor"].iloc[0] == 0.85
    assert "failing open" in caplog.text


def test_missing_column_raises():
    with pytest.raises(ValueError, match="wti_chg_21d"):
        gate_factors(_feats([1.0], [0.0], [0.0]).drop(columns="wti_chg_21d"), CFG)
