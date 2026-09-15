"""Per-factor Schmitt trigger (brief v2, decision 4b)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.golden import assert_golden
from tests.synthetic import make_config
from thematic_alpha.strategy.macro_gate import engaged_states, gate_factors, schmitt


def _s(values):
    return pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)


def test_engages_above_engage_and_holds_inside_the_band_both_ways():
    # 25 / 20 band. 22 from below: stays released; 22 from above: stays engaged.
    s = _s([18, 22, 24, 25, 26, 24, 22, 20.5, 20, 22, 19, 30, 25, 20])
    got = schmitt(s, 25.0, 20.0).tolist()
    assert got == [
        False,
        False,
        False,
        False,  # 25 is not above 25
        True,  # 26 engages
        True,  # 24 inside the band: hold
        True,  # 22 inside the band: hold
        True,  # 20.5 inside the band: hold
        False,  # 20 is at the release level: release
        False,  # 22 inside the band from below: hold (released)
        False,
        True,
        True,  # 25 inside the band from above: hold
        False,
    ]


def test_release_equal_to_engage_is_the_plain_comparator():
    rng = np.random.default_rng(0)
    s = _s(rng.normal(25, 5, 500))
    assert schmitt(s, 25.0, 25.0).tolist() == (s > 25.0).tolist()


def test_nan_fails_open_and_restarts_released(caplog):
    s = _s([30, np.nan, 24, 26])
    assert schmitt(s, 25.0, 20.0).tolist() == [True, False, False, True]  # 24 after NaN: released
    cfg = make_config().macro_gate
    idx = s.index
    feats = pd.DataFrame(
        {"vix_level": s, "dgs10_chg_21d": 0.0, "wti_chg_21d": [0.3, 0.18, np.nan, 0.18]}, index=idx
    )
    with caplog.at_level("WARNING"):
        e = engaged_states(feats, cfg)
    assert "failing open" in caplog.text
    assert e["oil_engaged"].tolist() == [True, True, False, False]  # band 0.20/0.16 holds at 0.18


def test_engaged_states_use_the_configured_release_thresholds():
    cfg = make_config().macro_gate  # chosen: 25/20, 0.40/0.32, 0.20/0.16
    assert (cfg.release_threshold("vix"), cfg.release_threshold("yield")) == (20.0, 0.32)
    idx = pd.bdate_range("2024-01-01", periods=3)
    feats = pd.DataFrame(
        {"vix_level": [26.0, 21.0, 21.0], "dgs10_chg_21d": [0.5, 0.35, 0.3], "wti_chg_21d": 0.0},
        index=idx,
    )
    f = gate_factors(feats, cfg)
    assert f["vix_engaged"].tolist() == [True, True, True]
    assert f["yield_engaged"].tolist() == [True, True, False]
    assert f["exposure"].tolist() == pytest.approx([0.35, 0.35, 0.5])


def test_release_above_engage_is_rejected():
    with pytest.raises(ValueError):
        make_config(macro_gate={"vix_release_threshold": 26.0})


def test_state_at_t_is_unchanged_by_future_data():
    rng = np.random.default_rng(3)
    s = _s(rng.normal(23, 4, 400))
    full = schmitt(s, 25.0, 20.0)
    for cut in (100, 250, 399):
        part = schmitt(s.iloc[: cut + 1], 25.0, 20.0)
        pd.testing.assert_series_equal(part, full.iloc[: cut + 1])


def test_release_equal_engage_is_golden():
    assert_golden(
        macro_gate={
            "vix_release_threshold": 25.0,
            "yield_release_threshold": 0.40,
            "oil_release_threshold": 0.20,
        }
    )
