"""Universe file loading and regime-start truncation.

The ranker-side exclusion test (tickers with insufficient history are excluded and the remaining
weights renormalize) is added in Layer 1C.
"""

from __future__ import annotations

import pandas as pd
import pytest

from thematic_alpha.data import universe as uni

CSV = """ticker,name,segment,exchange,currency,regime_start_date,notes
AAA,A Corp,compute,NASDAQ,USD,,
BBB,B Corp,memory,KRX,KRW,2021-06-01,pivot
"""


@pytest.fixture
def universe_file(tmp_path):
    p = tmp_path / "universe.csv"
    p.write_text(CSV)
    return p


def test_load_universe_maps(universe_file):
    u = uni.load_universe(universe_file)
    assert u.tickers == ["AAA", "BBB"]
    assert u.exchange_of == {"AAA": "NASDAQ", "BBB": "KRX"}
    assert u.currency_of == {"AAA": "USD", "BBB": "KRW"}
    assert u.regime_start == {"BBB": pd.Timestamp("2021-06-01")}


def test_missing_column_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("ticker,name\nAAA,A\n")
    with pytest.raises(ValueError, match="missing required columns"):
        uni.load_universe(p)


def test_duplicate_ticker_raises(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("ticker,name,segment,exchange,currency\nAAA,A,x,NYSE,USD\nAAA,A,x,NYSE,USD\n")
    with pytest.raises(ValueError, match="duplicate"):
        uni.load_universe(p)


def test_apply_regime_start_truncates_only_flagged(universe_file):
    u = uni.load_universe(universe_file)
    idx = pd.bdate_range("2021-05-28", periods=5)
    frames = {t: pd.DataFrame({"Close": range(5)}, index=idx) for t in ["AAA", "BBB"]}
    out = uni.apply_regime_start(frames, u)
    assert len(out["AAA"]) == 5
    assert out["BBB"].index.min() == pd.Timestamp("2021-06-01")


def test_short_history_excluded_and_weights_renormalize():
    """SPEC §9 test_universe: insufficient history -> excluded; survivors renormalize."""
    from tests.synthetic import build_features, make_config, make_market
    from thematic_alpha.strategy.ranker import rank

    market = make_market()
    cfg = make_config(
        data={"min_history_days": 100}, ranker={"top_n": 2, "weighting": "conviction_tier"}
    )
    feats = build_features(market, cfg)
    # Cut BBB's history so it only has ~50 sessions: it must never be held.
    raw = dict(market.raw)
    raw["BBB"] = raw["BBB"].iloc[-50:]
    from tests.synthetic import Market
    from thematic_alpha.data.prices import build_price_panel

    short = Market(
        master=market.master,
        sessions_of=market.sessions_of,
        raw=raw,
        panel=build_price_panel(raw, market.master, market.sessions_of),
        dollar_volume=market.dollar_volume,
        macro=market.macro,
        currency_of=market.currency_of,
    )
    feats_short = build_features(short, cfg)
    assert not feats_short.eligible["BBB"].any()
    w_full = rank(feats.wide, feats.eligible, cfg.ranker)
    w_short = rank(feats_short.wide, feats_short.eligible, cfg.ranker)
    last = market.master[-1]
    assert w_full.loc[last].tolist() == pytest.approx([0.30 / 0.55, 0.25 / 0.55]) or w_full.loc[
        last
    ].tolist() == pytest.approx([0.25 / 0.55, 0.30 / 0.55])
    assert w_short.loc[last].tolist() == pytest.approx([1.0, 0.0])  # renormalized to same total
    assert w_short.sum(axis=1).max() == pytest.approx(1.0)


def test_real_universe_file_loads():
    from tests.conftest import PROJECT_ROOT

    u = uni.load_universe(PROJECT_ROOT / "data" / "reference" / "universe.csv")
    assert "NVDA" in u.tickers and u.currency_of["000660.KS"] == "KRW"
