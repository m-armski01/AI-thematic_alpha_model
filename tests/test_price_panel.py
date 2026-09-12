"""Phantom-bar filter, wide panel construction, and the data-quality row."""

from __future__ import annotations

import numpy as np
import pandas as pd

from thematic_alpha.data import prices, quality


def _idx(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) for d in days])


def _ohlcv(index, close, volume):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Adj Close": close / 2,  # 2:1 adjustment factor makes adj_open checkable
            "Volume": volume,
        },
        index=index,
    )


def test_drop_phantom_bars_removes_only_zero_volume_non_sessions():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-05")
    df = _ohlcv(
        _idx("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
        [1, 2, 2, 3],
        [10, 10, 0, 10],
    )
    out = prices.drop_phantom_bars(df, own)
    assert pd.Timestamp("2024-01-04") not in out.index
    # A non-session bar WITH volume is kept (the calendar may be wrong, not the data).
    df2 = df.copy()
    df2.loc["2024-01-04", "Volume"] = 5
    assert pd.Timestamp("2024-01-04") in prices.drop_phantom_bars(df2, own).index


def test_build_price_panel_aligns_and_adjusts_open():
    nyse = _idx("2024-01-02", "2024-01-03", "2024-01-04")
    krx = _idx("2024-01-02", "2024-01-04")  # 01-03 KRX holiday
    master = nyse
    frames = {
        "US": _ohlcv(nyse, [10, 11, 12], [1, 1, 1]),
        "KR": _ohlcv(krx, [100, 102], [1, 1]),
    }
    panel = prices.build_price_panel(frames, master, {"US": nyse, "KR": krx})
    assert panel.tickers == ["US", "KR"]
    assert panel.adj_close.index.equals(master)
    # KR forward-filled across its own holiday, so no return is booked that day.
    assert panel.adj_close.loc["2024-01-03", "KR"] == panel.adj_close.loc["2024-01-02", "KR"]
    # adj_open = Open * AdjClose / Close = (Close - 0.5) / 2
    assert panel.adj_open.loc["2024-01-02", "US"] == (10 - 0.5) / 2


def test_ticker_quality_flags_and_nonpositive():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
    df = _ohlcv(_idx("2024-01-02", "2024-01-03", "2024-01-05"), [10, 14, 14], [1, 1, 1])
    df.loc["2024-01-05", "Adj Close"] = -1.0
    q = quality.ticker_quality("T", "NYSE", df, own, threshold=0.25)
    assert q.gaps == 1 and q.longest_gap == 1
    assert q.coverage == 3 / 4
    assert [d.strftime("%Y-%m-%d") for d, _ in q.suspicious] == ["2024-01-03", "2024-01-05"]
    assert q.nonpositive_adj_close == 1
    macro = pd.DataFrame({"X": [1.0]}, index=_idx("2024-01-02"))
    text = quality.render_quality_report([q], macro, 0.25)
    assert "| T | NYSE |" in text and "adj close <= 0" in text
