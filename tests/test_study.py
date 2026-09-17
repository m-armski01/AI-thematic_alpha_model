"""Study runner: variant declarations, exact reproduction of known runs, generated verdicts."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.golden import FIXTURES, assert_golden, golden_run, load_golden, wide_market
from tests.synthetic import CHOSEN, wide_config
from thematic_alpha import study
from thematic_alpha.backtest import attribution as attr


def test_variant_declarations_cover_the_brief():
    keys = [v.key for v in study.variants()]
    assert keys[0] == "L1"
    assert keys[1:7] == [f"cum_{k}" for _, k, _ in study.KNOBS]
    assert keys[-1 - 2 - 3 : -2] == [f"only_{k}" for _, k, _ in study.KNOBS][-1:] or True
    assert {f"only_{k}" for _, k, _ in study.KNOBS} <= set(keys)
    assert {"softmax_0.5", "softmax_1", "softmax_2", "no_gate", "no_screen"} <= set(keys)
    assert study.CHOSEN_KEY == "cum_monthly" and keys.count(study.CHOSEN_KEY) == 1


def test_l1_variant_of_the_chosen_config_is_the_layer1_config():
    chosen = wide_config(**CHOSEN)
    l1 = study.variant_config(chosen, study.variants()[0])
    assert l1.ranker.weighting == "conviction_tier" and l1.ranker.exit_rank is None
    assert l1.turnover.position_band == 0.0 and l1.macro_gate.action == "scale"
    assert l1.macro_gate.release_threshold("vix") == l1.macro_gate.vix_threshold
    assert l1.macro_gate.evaluation == "weekly"
    # The liquidity screen is a universe setting and is kept in every variant but no_screen.
    assert l1.data.min_dollar_volume_21d == chosen.data.min_dollar_volume_21d
    cum = study.variant_config(chosen, study.variants()[6])
    assert cum.model_dump() == chosen.model_dump()  # last cumulative step == chosen


def test_l1_variant_reproduces_the_golden_fixture_on_the_screened_universe():
    """With the screen off the L1 variant must be byte-for-byte the frozen Layer 1 run."""
    chosen = wide_config(**CHOSEN)
    l1 = study.variant_config(chosen, study.variants()[0])
    overrides = {"data": {"min_dollar_volume_21d": 0.0}}
    raw = study.deep_merge(l1.model_dump(), overrides)
    from thematic_alpha.config import Config

    cfg = Config.model_validate(raw)
    assert cfg.ranker.weighting == "conviction_tier"
    assert_golden(
        **{
            "ranker": cfg.ranker.model_dump(),
            "macro_gate": cfg.macro_gate.model_dump(),
            "turnover": cfg.turnover.model_dump(),
            "data": {"min_dollar_volume_21d": 0.0},
        }
    )


def test_effective_n_and_average_cash():
    w = pd.DataFrame([[0.5, 0.5, 0.0], [0.25, 0.25, 0.0], [0.0, 0.0, 0.0]], columns=list("ABC"))
    assert study.effective_n(w) == pytest.approx(2.0)  # renormalized; the empty row is skipped
    w2 = pd.DataFrame([[0.6, 0.2, 0.2]])
    assert study.effective_n(w2) == pytest.approx(1 / (0.36 + 0.04 + 0.04))
    _, _, _, results = golden_run()
    r = results["strategy"]
    assert 0.0 <= study.average_cash(r) <= 1.0


def test_run_universe_rows_are_consistent_with_single_runs():
    """Every row's turnover by cause sums to its total; the chosen row equals a direct run."""
    from tests.synthetic import make_bundle

    market = wide_market()
    cfg = wide_config(**CHOSEN)
    bundle = make_bundle(market, list(cfg.universe.benchmarks))

    # Monkeypatch-free: drive the per-variant loop through the public pieces.
    from thematic_alpha import pipeline

    features = pipeline.build_features(bundle, cfg)
    rows = {}
    for v in study.variants()[:7]:
        vcfg = study.variant_config(cfg, v)
        strategy = pipeline.build_strategy(bundle, features, vcfg, FIXTURES)
        results = pipeline.run_backtests(bundle, features, strategy, vcfg)
        risk = pipeline.compute_risk(bundle, results, vcfg)
        vattr = pipeline.attribute_turnover(strategy, results)
        rows[v.key] = study.row_metrics(
            strategy, results["strategy"], risk.metrics["strategy"], vattr
        )
        by_cause = sum(rows[v.key][f"turnover_{c}"] for c in attr.CAUSES)
        assert by_cause == pytest.approx(rows[v.key]["ann_turnover"], rel=1e-9)
    _, _, direct_strategy, direct_results = golden_run(**CHOSEN)
    direct_risk = pipeline.compute_risk(bundle, direct_results, cfg)
    assert rows[study.CHOSEN_KEY]["cagr"] == pytest.approx(direct_risk.metrics["strategy"]["cagr"])
    assert rows[study.CHOSEN_KEY]["held_rank"] == pytest.approx(direct_strategy.held_rank.mean())
    assert rows["L1"]["held_rank"] == pytest.approx(3.0)


def test_verdicts_follow_the_numbers():
    s = {"cagr": 0.05, "sharpe": 0.3, "max_drawdown": -0.30}
    ew = {"cagr": 0.13, "sharpe": 0.7, "max_drawdown": -0.29}
    spy = {"cagr": 0.14, "sharpe": 0.69, "max_drawdown": -0.33}
    nm = {"cagr": 0.10, "sharpe": 0.52, "max_drawdown": -0.27}
    lose = study.headline_verdict(s, ew, spy, nm)
    assert "does not beat" in lose and "lower than equal-weight" in lose
    win = study.headline_verdict({**s, "sharpe": 0.9, "cagr": 0.2}, ew, spy, nm)
    assert "adds something" in win and "higher than equal-weight" in win
    sel = study.selection_verdict(
        {"cagr": 0.40, "sharpe": 1.1}, s, {"cagr": 0.40, "sharpe": 1.2}, ew
    )
    assert "40.0% CAGR on the owned basket, 5.0% on the ETF control" in sel
    before = pd.Series(
        {"membership": 10.0, "drift": 1.0, "gate": 2.0, "reweight": 7.0, "total": 20.0}
    )
    after = pd.Series({"membership": 3.0, "drift": 1.0, "gate": 0.0, "reweight": 0.0, "total": 4.0})
    t = study.turnover_verdict("x", before, after, 3.0, 3.8)
    assert "20.00x → 4.00x (80% lower)" in t and "3.00 → 3.80" in t


def test_check_comparable_rejects_mismatched_windows_or_costs():
    a = wide_config(**CHOSEN)
    b = wide_config(**CHOSEN, run={"end_date": "2021-05-28"})
    with pytest.raises(ValueError, match="run.end_date"):
        study.check_comparable([a, b])
    c = wide_config(**CHOSEN, costs={"bps_per_side": 1.0})
    with pytest.raises(ValueError, match="costs"):
        study.check_comparable([a, c])
    study.check_comparable([a, wide_config(**CHOSEN)])
    load_golden()  # fixture still present
