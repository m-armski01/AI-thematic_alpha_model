"""Prices cache tests — fully offline. `_fetch` (network) must never be called on a cache hit."""

from __future__ import annotations

import pytest

from thematic_alpha.data import prices


def _boom(*_args, **_kwargs):
    raise AssertionError("_fetch (network) must not be called on a fresh-cache path")


def test_fresh_cache_reloads_without_network(tmp_path, synthetic_ohlcv, monkeypatch):
    monkeypatch.setattr(prices, "_fetch", _boom)

    cache_dir = tmp_path / "cache"
    prices._write_cache(prices._cache_path(cache_dir, "TEST"), synthetic_ohlcv)

    df, report = prices.load_ticker(
        ticker="TEST",
        start="2020-01-01",
        end=None,
        cache_dir=cache_dir,
        max_cache_age_days=1,
        refresh=False,
    )

    assert report.from_cache is True
    assert report.rows == len(synthetic_ohlcv)
    assert list(df.columns) == list(synthetic_ohlcv.columns)
    assert df["Close"].round(6).tolist() == synthetic_ohlcv["Close"].round(6).tolist()


def test_refresh_flag_forces_fetch(tmp_path, synthetic_ohlcv, monkeypatch):
    calls: list[str] = []

    def fake_fetch(ticker, start, end):
        calls.append(ticker)
        return synthetic_ohlcv

    monkeypatch.setattr(prices, "_fetch", fake_fetch)

    cache_dir = tmp_path / "cache"
    prices._write_cache(prices._cache_path(cache_dir, "TEST"), synthetic_ohlcv)

    _, report = prices.load_ticker(
        ticker="TEST",
        start="2020-01-01",
        end=None,
        cache_dir=cache_dir,
        max_cache_age_days=1,
        refresh=True,
    )

    assert calls == ["TEST"]
    assert report.from_cache is False


def test_stale_cache_triggers_fetch(tmp_path, synthetic_ohlcv, monkeypatch):
    import os
    import time

    calls: list[str] = []

    def fake_fetch(ticker, start, end):
        calls.append(ticker)
        return synthetic_ohlcv

    monkeypatch.setattr(prices, "_fetch", fake_fetch)

    cache_dir = tmp_path / "cache"
    path = prices._cache_path(cache_dir, "TEST")
    prices._write_cache(path, synthetic_ohlcv)

    # Backdate the cache file to 10 days old; max_cache_age_days=1 => stale.
    old = time.time() - 10 * 86400
    os.utime(path, (old, old))

    prices.load_ticker(
        ticker="TEST",
        start="2020-01-01",
        end=None,
        cache_dir=cache_dir,
        max_cache_age_days=1,
        refresh=False,
    )

    assert calls == ["TEST"]


def test_ticker_report_counts(synthetic_ohlcv):
    report = prices._ticker_report("TEST", synthetic_ohlcv, from_cache=True)
    assert report.rows == len(synthetic_ohlcv)
    assert report.missing_business_days == 0  # fixture uses contiguous business days


@pytest.mark.parametrize("refresh", [False, True])
def test_empty_download_not_cached(tmp_path, monkeypatch, refresh):
    import pandas as pd

    monkeypatch.setattr(prices, "_fetch", lambda *a, **k: pd.DataFrame())
    cache_dir = tmp_path / "cache"

    df, report = prices.load_ticker(
        ticker="EMPTY",
        start="2020-01-01",
        end=None,
        cache_dir=cache_dir,
        max_cache_age_days=1,
        refresh=refresh,
    )

    assert df.empty
    assert report.rows == 0
    assert not prices._cache_path(cache_dir, "EMPTY").exists()
