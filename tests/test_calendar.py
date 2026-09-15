"""Master calendar + alignment rules: union of sessions, ffill only on foreign holidays."""

from __future__ import annotations

import numpy as np
import pandas as pd

from thematic_alpha.data import calendar as cal


def _idx(*days: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) for d in days])


def test_master_calendar_is_sorted_union():
    a = _idx("2024-01-02", "2024-01-03", "2024-01-05")
    b = _idx("2024-01-03", "2024-01-04")
    master = cal.master_calendar([a, b])
    assert master.tolist() == _idx("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05").tolist()


def test_align_ffills_only_on_non_own_sessions():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-05")  # 01-04 is this exchange's holiday
    master = _idx("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=own)
    out = cal.align_to_master(df, own, master)
    # Foreign-only day gets the previous close (no return across it)...
    assert out.loc["2024-01-04", "Close"] == 2.0
    assert out.loc["2024-01-05", "Close"] == 3.0


def test_align_leaves_missing_own_session_nan():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-04")
    master = own
    df = pd.DataFrame({"Close": [1.0, 3.0]}, index=_idx("2024-01-02", "2024-01-04"))
    out = cal.align_to_master(df, own, master)
    assert np.isnan(out.loc["2024-01-03", "Close"])  # a real gap stays a gap


def test_align_never_backfills_before_first_observation():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-04")
    master = own
    df = pd.DataFrame({"Close": [5.0]}, index=_idx("2024-01-04"))
    out = cal.align_to_master(df, own, master)
    assert out["Close"].isna().tolist() == [True, True, False]


def test_missing_and_longest_gap():
    own = _idx("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08")
    present = _idx("2024-01-02", "2024-01-05", "2024-01-08")
    assert cal.missing_sessions(present, own) == 2
    assert cal.longest_gap(present, own) == 2


def test_exchange_sessions_real_calendars_differ():
    # 2024-01-01 is a holiday on both; 2024-01-15 (MLK) is NYSE-only; XKRX trades that day.
    nyse = cal.exchange_sessions("XNYS", "2024-01-01", "2024-01-31")
    krx = cal.exchange_sessions("XKRX", "2024-01-01", "2024-01-31")
    assert pd.Timestamp("2024-01-15") not in nyse
    assert pd.Timestamp("2024-01-15") in krx
    master = cal.master_calendar([nyse, krx])
    assert pd.Timestamp("2024-01-15") in master
    assert nyse.tz is None and krx.tz is None
