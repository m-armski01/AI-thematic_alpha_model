"""REQUIRED (SPEC §9): the feature panel at date t uses only data through the close of t.

(a) Shifting all inputs forward by one day changes the outputs (and reproduces the previous row).
(b) Feature values at t are unchanged when all data after t is deleted.
(c) A synthetic future spike produces no feature/signal change before the spike.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import (
    CHOSEN,
    LAYER1_NEUTRAL,
    Market,
    build_features,
    make_config,
    make_market,
    truncate,
)
from thematic_alpha.data.prices import build_price_panel


@pytest.fixture(scope="module")
def config():
    return make_config(data={"min_history_days": 100})


@pytest.fixture(scope="module")
def market():
    return make_market()


@pytest.fixture(scope="module")
def baseline(market, config):
    return build_features(market, config).tidy


def _shift_inputs(market: Market) -> Market:
    """Every input's value for day i is moved to day i+1 (sessions unchanged)."""
    raw = {}
    for t, df in market.raw.items():
        own = market.sessions_of[t]
        shifted = df.reindex(own).shift(1).dropna(how="all")
        raw[t] = shifted
    panel = build_price_panel(raw, market.master, market.sessions_of)
    return Market(
        master=market.master,
        sessions_of=market.sessions_of,
        raw=raw,
        panel=panel,
        dollar_volume=market.dollar_volume.shift(1),
        macro=market.macro.shift(1),
        currency_of=market.currency_of,
    )


def test_a_shifting_inputs_changes_outputs(market, config, baseline):
    shifted = build_features(_shift_inputs(market), config).tidy
    assert not shifted.equals(baseline)
    # AAA trades every master day, so its shifted row at t must equal the baseline row at t-1
    # for every pure price feature — i.e. the outputs move with the inputs, not the calendar.
    cols = ["ret_1d", "ret_21d", "mom_63", "vol_21", "px_to_ma_50", "dist_from_252d_high"]
    t, t_prev = market.master[-1], market.master[-2]
    got = shifted.loc[(t, "AAA"), cols].astype(float)
    exp = baseline.loc[(t_prev, "AAA"), cols].astype(float)
    pd.testing.assert_series_equal(got, exp, check_names=False)
    # ...and macro features shift the same way.
    assert shifted.loc[(t, "AAA"), "vix_level"] == baseline.loc[(t_prev, "AAA"), "vix_level"]


@pytest.mark.parametrize("pos", [320, 451, 599, 699])
def test_b_deleting_future_data_leaves_past_unchanged(market, config, baseline, pos):
    t = market.master[pos]
    truncated = build_features(truncate(market, t), config).tidy
    past = baseline.loc[baseline.index.get_level_values("date") <= t]
    pd.testing.assert_frame_equal(truncated, past, check_dtype=False)


def test_d_engine_never_trades_before_signal_plus_lag(market, config):
    """A price shock after the signal date cannot affect the trade that the signal produced."""
    from thematic_alpha.backtest.engine import run_backtest

    close = market.panel.adj_close[["AAA", "BBB"]]
    open_ = market.panel.adj_open[["AAA", "BBB"]]
    sig = market.master[100]
    tw = pd.DataFrame({"AAA": [0.6], "BBB": [0.4]}, index=[sig])
    bt = config.backtest.model_copy(update={"execution_lag_days": 1, "execution_price": "open"})
    base = run_backtest(close, tw, bt, config.costs, prices_open=open_)
    shocked_close, shocked_open = close.copy(), open_.copy()
    shocked_close.loc[market.master[102] :] *= 5  # shock strictly after execution (t+1)
    shocked_open.loc[market.master[102] :] *= 5
    shocked = run_backtest(shocked_close, tw, bt, config.costs, prices_open=shocked_open)
    pd.testing.assert_frame_equal(base.trades, shocked.trades)
    assert base.trades["date"].unique().tolist() == [market.master[101]]
    pd.testing.assert_series_equal(
        base.equity_curve.loc[: market.master[101]], shocked.equity_curve.loc[: market.master[101]]
    )


def test_c_future_spike_leaves_no_trace_before_it(market, config, baseline):
    spike_at = market.master[500]
    raw = {t: df.copy() for t, df in market.raw.items()}
    aaa = raw["AAA"]
    aaa.loc[aaa.index >= spike_at, ["Open", "High", "Low", "Close", "Adj Close"]] *= 3.0
    spiked = Market(
        master=market.master,
        sessions_of=market.sessions_of,
        raw=raw,
        panel=build_price_panel(raw, market.master, market.sessions_of),
        dollar_volume=market.dollar_volume,
        macro=market.macro,
        currency_of=market.currency_of,
    )
    out = build_features(spiked, config).tidy
    dates = out.index.get_level_values("date")
    before, after = dates < spike_at, dates >= spike_at
    pd.testing.assert_frame_equal(out[before], baseline[before], check_dtype=False)
    # Sanity: the spike is visible once it happens (otherwise the test proves nothing).
    assert out.loc[(spike_at, "AAA"), "ret_1d"] > 1.5
    assert not np.allclose(
        out[after]["mom_rank"].fillna(-1).to_numpy(),
        baseline[after]["mom_rank"].fillna(-1).to_numpy(),
    )


# --- strategy level (brief v2): stateful selection and the gate are pure functions of history.


@pytest.mark.parametrize("settings", [LAYER1_NEUTRAL, CHOSEN], ids=["neutral", "chosen"])
@pytest.mark.parametrize("pos", [599, 779])  # Fridays: the cut week is a complete signal week
def test_e_strategy_targets_and_trades_unchanged_when_future_is_deleted(settings, pos):
    from tests.golden import FIXTURES, wide_market
    from tests.synthetic import run_pipeline, wide_config

    market = wide_market()
    cfg = wide_config(**settings)
    _, _, full_strategy, full_results = run_pipeline(market, cfg, FIXTURES)
    t = market.master[pos]
    assert t.weekday() == 4
    cut_cfg = wide_config(**settings, run={"end_date": str(t.date())})
    _, _, cut_strategy, cut_results = run_pipeline(truncate(market, t), cut_cfg, FIXTURES)
    tw_full = full_strategy.target_weights.loc[:t]
    tw_cut = cut_strategy.target_weights
    pd.testing.assert_frame_equal(tw_cut, tw_full.loc[tw_cut.index])
    assert len(tw_cut) >= len(tw_full) - 1  # only the signal on t itself may be missing
    hr_full = full_strategy.held_rank.loc[:t]
    pd.testing.assert_series_equal(
        cut_strategy.held_rank, hr_full.loc[cut_strategy.held_rank.index]
    )
    trades_full = full_results["strategy"].trades
    trades_full = trades_full[trades_full["date"] <= t].reset_index(drop=True)
    pd.testing.assert_frame_equal(cut_results["strategy"].trades, trades_full)
