"""Rebalance schedule: weekly Friday with holiday roll-back, monthly, date bounds."""

from __future__ import annotations

import pandas as pd

from thematic_alpha.backtest.schedule import signal_dates

# Jan 2024 business days minus Fri 2024-01-19 (a pretend holiday) and Mon 01-15 (MLK).
SESSIONS = pd.bdate_range("2024-01-01", "2024-02-09").difference(
    pd.DatetimeIndex(["2024-01-19", "2024-01-15"])
)


def test_weekly_friday_rolls_back_on_holiday():
    out = signal_dates(SESSIONS, "weekly", "friday")
    got = out.strftime("%m-%d").tolist()
    assert "01-18" in got and "01-19" not in got  # Thursday stands in for the Friday holiday
    assert got[:2] == ["01-05", "01-12"]
    assert len(out) == 6


def test_weekly_monday_holiday_uses_first_session_of_week():
    out = signal_dates(SESSIONS, "weekly", "monday")
    assert pd.Timestamp("2024-01-16") in out  # Tuesday after MLK Monday


def test_monthly_takes_last_weekly_date_in_month():
    out = signal_dates(SESSIONS, "monthly", "friday")
    assert out.strftime("%m-%d").tolist() == ["01-26", "02-09"]


def test_bounds():
    out = signal_dates(SESSIONS, "weekly", "friday", start="2024-01-10", end="2024-01-31")
    assert out.min() >= pd.Timestamp("2024-01-10") and out.max() <= pd.Timestamp("2024-01-31")
