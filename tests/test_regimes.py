"""Performance by regime: deterministic tags, bucket arithmetic, table shape, generated verdict."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import make_config
from thematic_alpha.reporting import report
from thematic_alpha.risk import regimes as rg
from thematic_alpha.risk.metrics import MIN_ANNUALISE_SESSIONS


def test_vix_tags_are_deterministic_and_nan_stays_untagged():
    idx = pd.bdate_range("2024-01-01", periods=6)
    vix = pd.Series([15.0, 20.0, 22.0, 25.0, 30.0, np.nan], index=idx)
    tags = rg.vix_regime(vix, calm=20.0, stress=25.0)
    assert list(tags.iloc[:5]) == ["calm", "elevated", "elevated", "elevated", "stress"]
    assert pd.isna(tags.iloc[5])


def test_gate_tags_carry_the_signal_date_state_forward():
    idx = pd.bdate_range("2024-01-01", periods=10)
    state = pd.Series([False, True, False], index=[idx[2], idx[4], idx[8]])  # block mode
    tags = rg.gate_regime(state, "block_increases", idx)
    expected = ["risk-on"] * 4 + ["risk-off"] * 4 + ["risk-on"] * 2  # before first signal: on
    assert list(tags) == expected
    scale = pd.Series([1.0, 0.5], index=[idx[0], idx[5]])
    assert list(rg.gate_regime(scale, "scale", idx)) == ["risk-on"] * 5 + ["risk-off"] * 5


def test_rate_tags_use_the_engage_threshold():
    idx = pd.bdate_range("2024-01-01", periods=4)
    chg = pd.Series([0.1, 0.4, 0.41, np.nan], index=idx)
    tags = rg.rate_regime(chg, 0.4)
    assert list(tags.iloc[:3]) == ["no shock", "no shock", "rate shock"] and pd.isna(tags.iloc[3])


def test_bucket_stats_by_hand_and_annualisation_guard():
    r = pd.Series([0.1, -0.05, 0.02])
    st = rg.bucket_stats(r, n_total=6)
    assert st["n_sessions"] == 3 and st["share"] == pytest.approx(0.5)
    assert st["total_return"] == pytest.approx(1.1 * 0.95 * 1.02 - 1)
    assert st["hit_rate"] == pytest.approx(2 / 3)
    assert st["max_drawdown"] == pytest.approx(-0.05)  # 1.1 -> 1.045
    assert np.isnan(st["ann_return"])  # far too short to annualise
    long = pd.Series(0.001, index=range(MIN_ANNUALISE_SESSIONS))
    assert rg.bucket_stats(long, MIN_ANNUALISE_SESSIONS)["ann_return"] == pytest.approx(
        1.001**252 - 1
    )
    empty = rg.bucket_stats(pd.Series(dtype=float), 10)
    assert empty["n_sessions"] == 0 and np.isnan(empty["total_return"])


def test_regime_table_shares_sum_to_one_and_rows_follow_label_order():
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(5)
    returns = {
        "strategy": pd.Series(rng.normal(0, 0.01, 300), index=idx),
        "equal_weight_bh": pd.Series(rng.normal(0, 0.01, 300), index=idx),
    }
    vix = pd.Series(np.where(np.arange(300) % 3 == 0, 30.0, 15.0), index=idx)
    tags = rg.vix_regime(vix, 20.0, 25.0)
    table = rg.regime_table(returns, tags, rg.VIX_LABELS)
    assert list(table.index.get_level_values("regime")) == [
        "calm",
        "calm",
        "elevated",
        "elevated",
        "stress",
        "stress",
    ]
    strat = table.xs("strategy", level="run")
    assert strat["share"].sum() == pytest.approx(1.0)
    assert strat.loc["elevated", "n_sessions"] == 0 and np.isnan(
        strat.loc["elevated", "total_return"]
    )
    assert strat.loc["stress", "n_sessions"] == 100


def test_compute_regimes_end_to_end_and_report_section():
    cfg = make_config()
    idx = pd.bdate_range("2024-01-01", periods=120)
    rng = np.random.default_rng(9)
    returns = {
        "strategy": pd.Series(rng.normal(0.001, 0.01, 120), index=idx),
        "equal_weight_bh": pd.Series(rng.normal(0.0, 0.01, 120), index=idx),
    }
    macro = pd.DataFrame(
        {
            "vix_level": np.where(np.arange(120) < 60, 15.0, 30.0),
            "dgs10_chg_21d": np.where(np.arange(120) % 2 == 0, 0.0, 0.6),
        },
        index=idx,
    )
    state = pd.Series([False, True], index=[idx[0], idx[60]])
    out = rg.compute_regimes(
        returns,
        idx,
        macro,
        state,
        "block_increases",
        vix_calm=20.0,
        vix_stress=25.0,
        rate_column="dgs10_chg_21d",
        rate_threshold=0.4,
    )
    assert set(out) == {"vix", "gate", "rates"}
    assert out["vix"].loc[("stress", "strategy"), "share"] == pytest.approx(0.5)
    assert out["gate"].loc[("risk-off", "strategy"), "n_sessions"] == 60
    md = report.regime_markdown(out["vix"])
    assert md.startswith("| Regime | Run |") and "| stress | Overlay |" in md
    verdict = report._regime_verdict(out)
    assert "In the VIX stress regime (50.0% of sessions)" in verdict
    assert any(k in verdict for k in ("helps specifically", "does not help", "mixed"))
    assert report._regime_verdict({}) == "No stress bucket has enough sessions to compare."
    assert report._regime_intro(cfg).startswith("The overlay is a macro-timing rule")
