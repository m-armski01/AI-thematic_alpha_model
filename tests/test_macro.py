"""FRED loader: parsing, cache hit is offline, forward-fill only, publication lag."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from thematic_alpha.data import macro
from thematic_alpha.data.cache import cache_path, write_cache


def _boom(*_a, **_k):
    raise AssertionError("_fetch (network) must not be called on a cache hit")


def test_fetch_parses_fredgraph_csv(monkeypatch):
    csv = "observation_date,VIXCLS\n2024-01-02,13.2\n2024-01-03,.\n2024-01-04,14.0\n"
    real_read_csv = pd.read_csv
    monkeypatch.setattr(pd, "read_csv", lambda url, **kw: real_read_csv(io.StringIO(csv), **kw))
    df = macro._fetch("VIXCLS")
    assert list(df.columns) == ["VIXCLS"]
    assert df.index.name == "date"
    assert np.isnan(df.loc["2024-01-03", "VIXCLS"])
    assert df.loc["2024-01-04", "VIXCLS"] == 14.0


def test_cache_hit_makes_no_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr(macro, "_fetch", _boom)
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date")
    write_cache(cache_path(tmp_path, "macro", "DGS10"), pd.DataFrame({"DGS10": [4.0, 4.1]}, idx))
    s = macro.load_series("DGS10", tmp_path, max_cache_age_days=1)
    assert s.tolist() == [4.0, 4.1]


def test_refresh_downloads_and_caches(tmp_path, monkeypatch):
    calls = []

    def fake(sid):
        calls.append(sid)
        idx = pd.DatetimeIndex(["2024-01-02"], name="date")
        return pd.DataFrame({sid: [1.0]}, idx)

    monkeypatch.setattr(macro, "_fetch", fake)
    df = macro.load_macro(["DGS10", "VIXCLS"], tmp_path, 1, refresh=True)
    assert calls == ["DGS10", "VIXCLS"]
    assert list(df.columns) == ["DGS10", "VIXCLS"]
    assert cache_path(tmp_path, "macro", "VIXCLS").exists()


@pytest.fixture
def master():
    return pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])


def test_align_forward_fills_only(master):
    # Obs on 01-03 and 01-05 only; 01-02 must stay NaN (no back-fill), 01-04 takes 01-03.
    raw = pd.DataFrame({"X": [1.0, 2.0]}, index=pd.DatetimeIndex(["2024-01-03", "2024-01-05"]))
    out = macro.align_macro(raw, master, lag=0)
    assert out["X"].isna().tolist() == [True, False, False, False]
    assert out["X"].tolist()[1:] == [1.0, 1.0, 2.0]


def test_align_carries_non_session_observation_forward(master):
    # An observation dated on a non-session day (weekend/holiday) reaches the next session.
    raw = pd.DataFrame({"X": [7.0]}, index=pd.DatetimeIndex(["2024-01-01"]))
    out = macro.align_macro(raw, master, lag=0)
    assert out["X"].tolist() == [7.0] * 4


def test_publication_lag_shifts_by_sessions(master):
    raw = pd.DataFrame({"X": [1.0, 2.0, 3.0, 4.0]}, index=master)
    out = macro.align_macro(raw, master, lag=1)
    assert np.isnan(out["X"].iloc[0])
    assert out["X"].tolist()[1:] == [1.0, 2.0, 3.0]
