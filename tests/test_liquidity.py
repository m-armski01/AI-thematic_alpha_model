"""Liquidity screen (brief v2, decision 7) and the per-ticker first-eligible dates."""

from __future__ import annotations

import pandas as pd

from tests.golden import assert_golden, golden_run, wide_market
from tests.synthetic import WIDE_ILLIQUID, WIDE_LISTING, make_bundle
from thematic_alpha import pipeline
from thematic_alpha.data.calendar import EXCHANGE_TO_MIC, mic_for
from thematic_alpha.data.universe import load_universe
from thematic_alpha.features.build import eligibility


def test_threshold_binds_only_on_the_illiquid_name():
    market = wide_market()
    adv = market.dollar_volume.rolling(21).mean()
    threshold = 1e6  # the illiquid name trades < 3e5 per day; every other name > 7e6
    _, feats_on, _, _ = golden_run(data={"min_dollar_volume_21d": threshold})
    _, feats_off, _, _ = golden_run(data={"min_dollar_volume_21d": 0.0})
    assert not feats_on.eligible[WIDE_ILLIQUID].any()
    assert feats_off.eligible[WIDE_ILLIQUID].any()
    others = [t for t in feats_on.eligible.columns if t != WIDE_ILLIQUID]
    pd.testing.assert_frame_equal(feats_on.eligible[others], feats_off.eligible[others])
    assert (
        (adv.loc[feats_on.eligible.index, others].fillna(0) >= threshold)
        .where(feats_on.eligible[others])
        .fillna(True)
        .all()
        .all()
    )


def test_eligibility_helper_applies_liquidity_only_when_positive():
    idx = pd.bdate_range("2024-01-01", periods=3)
    hist = pd.DataFrame({"A": [300, 300, 300]}, index=idx)
    dv = pd.DataFrame({"A": [1e6, 1e4, float("nan")]}, index=idx)
    off = eligibility(hist, 252, dollar_volume_21d=dv, min_dollar_volume_21d=0.0)
    on = eligibility(hist, 252, dollar_volume_21d=dv, min_dollar_volume_21d=1e5)
    assert off["A"].tolist() == [True, True, True]
    assert on["A"].tolist() == [True, False, False]  # NaN ADV is not eligible


def test_first_dates_table_reports_the_four_milestones():
    _, feats, _, _ = golden_run(data={"min_dollar_volume_21d": 1e6})
    fd = feats.first_dates
    assert list(fd.columns) == [
        "first_price",
        "first_history_eligible",
        "first_liquidity_eligible",
        "first_eligible",
    ]
    market = wide_market()
    for t, pos in WIDE_LISTING.items():
        assert fd.loc[t, "first_price"] == market.master[pos]
        assert fd.loc[t, "first_history_eligible"] == market.master[pos + 251]
        assert fd.loc[t, "first_eligible"] >= fd.loc[t, "first_history_eligible"]
    assert pd.isna(fd.loc[WIDE_ILLIQUID, "first_liquidity_eligible"])
    assert pd.isna(fd.loc[WIDE_ILLIQUID, "first_eligible"])
    fe = fd["first_eligible"].dropna()
    assert (fe >= fd.loc[fe.index, "first_history_eligible"]).all()


def test_etf_universe_file_loads_and_every_venue_maps_to_the_nyse_calendar():
    from tests.conftest import PROJECT_ROOT

    u = load_universe(PROJECT_ROOT / "data" / "reference" / "universe_etf.csv")
    assert len(u.tickers) == 17
    assert {u.segment_of[t] for t in ("TLT", "GLD")} == {"defensive"}
    assert sum(seg == "sector" for seg in u.segment_of.values()) == 11
    assert sum(seg == "thematic" for seg in u.segment_of.values()) == 4
    assert {mic_for(ex) for ex in u.exchange_of.values()} == {"XNYS"}
    assert "NYSE Arca" in EXCHANGE_TO_MIC and "Cboe BZX" in EXCHANGE_TO_MIC


def test_bundle_segments_reach_the_pipeline():
    bundle = make_bundle(wide_market())
    assert bundle.universe.segment_of["W07"] == "defensive"
    assert pipeline.STRATEGY == "strategy"


def test_liquidity_zero_is_golden():
    assert_golden(data={"min_dollar_volume_21d": 0.0})
