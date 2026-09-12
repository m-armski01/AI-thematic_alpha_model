"""Feature panel: hand-computed values, NaN on incomplete windows, own-session alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import MARKET, build_features, make_config, make_market
from thematic_alpha.features import macro_features as mf
from thematic_alpha.features import price_features as pf


@pytest.fixture(scope="module")
def market():
    return make_market()


@pytest.fixture(scope="module")
def config():
    return make_config(data={"min_history_days": 100})


@pytest.fixture(scope="module")
def features(market, config):
    return build_features(market, config)


def test_momentum_skips_recent_days():
    px = pd.DataFrame({"X": np.arange(1.0, 31.0)}, index=pd.bdate_range("2024-01-01", periods=30))
    out = pf.momentum(px, [10], skip=2)["mom_10"]
    # At t=29: px[27] / px[19] - 1 = 28/20 - 1
    assert out.iloc[29, 0] == pytest.approx(28 / 20 - 1)
    assert out.iloc[:10, 0].isna().all()


def test_momentum_window_must_exceed_skip():
    px = pd.DataFrame({"X": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2))
    with pytest.raises(ValueError):
        pf.momentum(px, [5], skip=5)


def test_vol_nan_until_window_full():
    px = pd.DataFrame({"X": np.exp(np.arange(30) * 0.01)}, index=pd.bdate_range("2024", periods=30))
    out = pf.realized_vol(px, [21])["vol_21"]
    assert out.iloc[:21, 0].isna().all()  # 21 returns need 22 prices
    assert out.iloc[21, 0] == pytest.approx(0.0, abs=1e-9)  # constant log return -> zero vol


def test_price_to_ma_and_high():
    px = pd.DataFrame({"X": [1.0, 2.0, 3.0, 4.0]}, index=pd.bdate_range("2024", periods=4))
    assert pf.price_to_ma(px, [2])["px_to_ma_2"].iloc[-1, 0] == pytest.approx(4 / 3.5 - 1)
    assert pf.dist_from_high(px, 3).iloc[-1, 0] == 0.0  # at the high


def test_rolling_beta_recovers_known_beta():
    idx = pd.bdate_range("2020", periods=300)
    rng = np.random.default_rng(1)
    m_ret = rng.normal(0, 0.01, 300)
    a_ret = 1.5 * m_ret
    m = pd.Series(100 * np.exp(np.cumsum(m_ret)), idx)
    a = pd.DataFrame({"A": 100 * np.exp(np.cumsum(a_ret))}, idx)
    beta = pf.rolling_beta(a, m, 60)
    assert beta.iloc[-1, 0] == pytest.approx(1.5, abs=0.02)


def test_krx_feature_forward_filled_on_own_holiday(market, features):
    holiday = market.master[36]  # BBB is closed on this master day
    prev = market.master[35]
    assert holiday not in market.sessions_of["BBB"]
    for name in ["ret_1d", "mom_63", "vol_21"]:
        wide = features.wide[name]
        a, b = wide.loc[holiday, "BBB"], wide.loc[prev, "BBB"]
        assert (np.isnan(a) and np.isnan(b)) or a == b
    # ...while AAA has a fresh value that generally differs from its previous day.
    assert features.wide["ret_1d"].loc[holiday, "AAA"] != features.wide["ret_1d"].loc[prev, "AAA"]


def test_windows_count_own_sessions_not_master_days(market, features):
    # BBB's 21-day vol on a given date must equal the vol computed on its own 21 sessions.
    own = market.sessions_of["BBB"]
    t = own[300]
    px = market.raw["BBB"]["Adj Close"].loc[:t]
    expected = px.pct_change().iloc[-21:].std(ddof=1) * np.sqrt(252)
    assert features.wide["vol_21"].loc[t, "BBB"] == pytest.approx(expected)


def test_eligibility_and_ranks(features, config):
    elig = features.eligible
    hist = features.wide["history_days"]
    assert not elig[hist < config.data.min_history_days].any().any()
    late = elig.index[-1]
    assert elig.loc[late].all()
    ranks = features.wide["mom_rank"].loc[late]
    assert sorted(ranks.tolist()) == [0.5, 1.0]
    # Before eligibility no rank is assigned.
    early = elig.index[10]
    assert features.wide["mom_rank"].loc[early].isna().all()


def test_tidy_panel_shape_and_macro_broadcast(features, market):
    tidy = features.tidy
    assert tidy.index.names == ["date", "ticker"]
    assert len(tidy) == len(market.master) * 2
    t = market.master[-1]
    assert tidy.loc[(t, "AAA"), "vix_level"] == tidy.loc[(t, "BBB"), "vix_level"]
    assert tidy.loc[(t, "AAA"), "vix_level"] == market.macro.loc[t, "VIXCLS"]
    for col in [
        "ret_1d",
        "mom_63",
        "vol_21",
        "px_to_ma_50",
        "dist_from_252d_high",
        "beta_60d",
        "dollar_volume_21d",
        "mom_rank",
        "vol_rank",
        "dgs10_chg_21d",
        "wti_chg_21d",
        "vix_percentile_252d",
        "dxy_chg_21d",
    ]:
        assert col in tidy.columns, col


def test_wti_change_floors_denominator_only():
    idx = pd.bdate_range("2024", periods=30)
    macro = pd.DataFrame(
        1.0, index=idx, columns=["DGS10", "T10Y2Y", "VIXCLS", "T10YIE", "DTWEXBGS"]
    )
    macro["DCOILWTICO"] = 50.0
    macro.iloc[5, macro.columns.get_loc("DCOILWTICO")] = -37.0  # the 2020-04-20 print
    out = mf.compute_macro_features(macro, mf.MacroFeatureSpec(21, 21))
    chg = out["wti_chg_21d"]
    assert chg.iloc[5 + 21] == pytest.approx(50 / mf.WTI_PRICE_FLOOR - 1)  # base floored
    assert chg.iloc[26 - 21 + 21 - 1] == pytest.approx(0.0)  # normal day unaffected


def test_market_ticker_required(market, config):
    from thematic_alpha.features.build import build_feature_panel

    with pytest.raises(ValueError, match="market ticker"):
        build_feature_panel(
            market.panel,
            market.dollar_volume,
            market.macro,
            market.sessions_of,
            market.master,
            ["AAA"],
            config,
            market_ticker="NOPE",
        )
    assert MARKET in market.panel.adj_close.columns
