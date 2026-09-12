"""FX conversion: rate math, the KRW->EUR chain, and separability of the FX contribution."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from thematic_alpha.data import fx


@pytest.fixture
def rates():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame({"DEXUSEU": [1.10, 1.10, 1.20], "DEXKOUS": [1300.0, 1300.0, 1300.0]}, idx)


def test_usd_to_eur(rates):
    r = fx.base_per_local("USD", "EUR", rates)
    assert r.iloc[0] == pytest.approx(1 / 1.10)


def test_krw_to_eur_chain(rates):
    r = fx.base_per_local("KRW", "EUR", rates)
    assert r.iloc[0] == pytest.approx(1 / (1300.0 * 1.10))


def test_same_currency_is_identity(rates):
    assert fx.base_per_local("EUR", "EUR", rates).tolist() == [1.0, 1.0, 1.0]


def test_missing_series_raises(rates):
    with pytest.raises(ValueError, match="DEXKOUS"):
        fx.base_per_local("KRW", "EUR", rates[["DEXUSEU"]])


def test_fx_contribution_separable(rates):
    prices = pd.DataFrame({"AAA": [100.0, 110.0, 110.0]}, index=rates.index)
    ret_local, ret_base = fx.local_and_base_returns(prices, {"AAA": "USD"}, "EUR", rates)
    # Day 2: pure stock move, FX flat -> identical returns.
    assert ret_local.iloc[1, 0] == pytest.approx(ret_base.iloc[1, 0])
    # Day 3: stock flat, EUR strengthens 1.10 -> 1.20 -> USD position loses in EUR terms.
    assert ret_local.iloc[2, 0] == 0.0
    assert ret_base.iloc[2, 0] == pytest.approx(1.10 / 1.20 - 1)
    contribution = ret_base - ret_local
    assert np.isnan(contribution.iloc[0, 0])
    assert contribution.iloc[2, 0] < 0
