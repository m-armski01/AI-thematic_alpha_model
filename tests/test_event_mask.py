"""Event mask: window placement, weekend events, fail-open warning, CSV loading."""

from __future__ import annotations

import pandas as pd

from thematic_alpha.strategy import event_mask as em

DATES = pd.bdate_range("2024-01-01", periods=15)  # Mon 01-01 .. Fri 01-19


def test_blocks_n_sessions_before_and_including_event():
    events = {"A": pd.DatetimeIndex(["2024-01-10"])}  # Wednesday, position 7
    m = em.build_event_mask(DATES, ["A"], events, block_days=3)
    blocked = m.blocked["A"]
    assert blocked[blocked].index.strftime("%m-%d").tolist() == ["01-05", "01-08", "01-09", "01-10"]
    assert m.failed_open == []


def test_weekend_event_maps_to_next_session():
    events = {"A": pd.DatetimeIndex(["2024-01-13"])}  # Saturday -> Monday 01-15
    m = em.build_event_mask(DATES, ["A"], events, block_days=1)
    assert m.blocked["A"][m.blocked["A"]].index.strftime("%m-%d").tolist() == ["01-12", "01-15"]


def test_event_after_range_ignored_and_zero_window():
    events = {"A": pd.DatetimeIndex(["2030-01-01", "2024-01-03"])}
    m = em.build_event_mask(DATES, ["A"], events, block_days=0)
    assert m.blocked["A"].sum() == 1


def test_missing_ticker_fails_open(caplog):
    with caplog.at_level("WARNING"):
        m = em.build_event_mask(DATES, ["A", "B"], {"A": pd.DatetimeIndex(["2024-01-10"])}, 3)
    assert m.failed_open == ["B"]
    assert not m.blocked["B"].any()
    assert "failing open" in caplog.text and "B" in caplog.text


def test_load_earnings_dates_parses_and_dedups(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("ticker,earnings_date\n# comment\nA,2024-02-21\nA,2024-02-21\nB,2024-05-01\n")
    out = em.load_earnings_dates(p)
    assert list(out) == ["A", "B"]
    assert out["A"].tolist() == [pd.Timestamp("2024-02-21")]


def test_load_empty_file(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("ticker,earnings_date\n# nothing yet\n")
    assert em.load_earnings_dates(p) == {}
