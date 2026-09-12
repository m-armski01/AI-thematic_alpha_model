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


def test_real_universe_file_loads():
    from tests.conftest import PROJECT_ROOT

    u = uni.load_universe(PROJECT_ROOT / "data" / "reference" / "universe.csv")
    assert "NVDA" in u.tickers and u.currency_of["000660.KS"] == "KRW"
