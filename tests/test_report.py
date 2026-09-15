"""End-to-end reporting smoke test on synthetic data: figures + report.md written offline."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tests.synthetic import make_config
from thematic_alpha.backtest.engine import run_backtest
from thematic_alpha.reporting import plots, report, tables
from thematic_alpha.risk import metrics as m
from thematic_alpha.risk.drawdown import drawdown_table, underwater


def _results():
    idx = pd.bdate_range("2022-01-03", periods=400)
    rng = np.random.default_rng(11)
    close = pd.DataFrame(
        {t: 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 400))) for t in ["A", "B", "C"]},
        index=idx,
    )
    close["^GSPC"] = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 400)))
    open_ = close * 1.001
    cfg = make_config()
    sig = idx[::5]
    out = {}
    tw_s = pd.DataFrame({"A": 0.4, "B": 0.3, "C": 0.2}, index=sig)
    out["strategy"] = run_backtest(close, tw_s, cfg.backtest, cfg.costs, open_)
    out["sp500"] = run_backtest(
        close, pd.DataFrame({"^GSPC": [1.0]}, index=[sig[0]]), cfg.backtest, cfg.costs, open_
    )
    tw_ew = pd.DataFrame({"A": [1 / 3], "B": [1 / 3], "C": [1 / 3]}, index=[sig[0]])
    out["equal_weight_bh"] = run_backtest(close, tw_ew, cfg.backtest, cfg.costs, open_)
    tw_nm = pd.DataFrame({"A": 0.5, "B": 0.5}, index=sig)
    out["naive_momentum"] = run_backtest(close, tw_nm, cfg.backtest, cfg.costs, open_)
    return cfg, close, out


def test_report_and_figures(tmp_path):
    cfg, close, results = _results()
    rf = pd.Series(0.0, index=close.index)
    mkt = close["^GSPC"].pct_change()
    metrics = {n: m.compute_metrics(r, rf, mkt, cfg.risk) for n, r in results.items()}
    drawdowns = {n: drawdown_table(r.equity_curve) for n, r in results.items()}
    strat = results["strategy"]
    fig_dir = tmp_path / "figures"
    figures = {
        "equity": plots.equity_curves(
            {n: r.equity_curve for n, r in results.items()}, report.LABELS, fig_dir / "eq.png"
        ),
        "underwater": plots.underwater(underwater(strat.equity_curve), fig_dir / "uw.png"),
        "rolling_sharpe": plots.rolling_line(
            m.rolling_sharpe(strat.daily_returns, 60), "s", "y", fig_dir / "rs.png", 0.0
        ),
        "rolling_beta": plots.rolling_line(
            m.rolling_beta(strat.daily_returns, mkt, 60), "b", "y", fig_dir / "rb.png", 1.0
        ),
        "weights": plots.weights_area(strat.weights_history, fig_dir / "w.png", max_named=2),
        "gate": plots.gate_and_vix(
            pd.Series(1.0, index=close.index),
            pd.Series(20.0, index=close.index),
            25.0,
            fig_dir / "g.png",
        ),
    }
    for p in figures.values():
        assert p.exists() and p.stat().st_size > 1000
    text = report.render_report(
        config=cfg,
        quality_summary={"n_tickers": 4, "n_macro": 11, "n_flagged": 3, "threshold": 0.25},
        strategy_summary={
            "n_signal_dates": 80,
            "exposure_mean": 0.9,
            "exposure_min": 0.3,
            "n_gated": 10,
            "entries_blocked": 5,
            "masked_ticker_dates": 40,
            "n_failed_open": 0,
        },
        metrics=metrics,
        drawdowns=drawdowns,
        fx=m.fx_contribution(strat, strat),
        figures=figures,
        figure_root=tmp_path,
    )
    path = report.write_report(text, tmp_path / "report.md")
    body = path.read_text()
    assert body.startswith("# thematic-alpha report")
    assert "Hindsight bias" in body.split("## Configuration")[0]  # caveat comes first
    header = [ln for ln in body.splitlines() if ln.startswith("| Metric |")][0]
    assert header.count("|") == 6  # Metric + 4 runs
    assert "5 entries blocked pre-earnings" in body
    assert "figures/eq.png" in body and "figures/g.png" in body
    assert "20" not in tables.fmt_date(pd.NaT) and tables.fmt_pct(float("nan")) == "n/a"


def test_report_is_deterministic(tmp_path):
    cfg, close, results = _results()
    kwargs = dict(
        config=cfg,
        quality_summary={"n_tickers": 4, "n_macro": 11, "n_flagged": 3, "threshold": 0.25},
        strategy_summary={
            "n_signal_dates": 80,
            "exposure_mean": 0.9,
            "exposure_min": 0.3,
            "n_gated": 10,
            "entries_blocked": 5,
            "masked_ticker_dates": 40,
            "n_failed_open": 0,
        },
        metrics={
            n: m.compute_metrics(
                r, pd.Series(0.0, index=close.index), close["^GSPC"].pct_change(), cfg.risk
            )
            for n, r in results.items()
        },
        drawdowns={n: drawdown_table(r.equity_curve) for n, r in results.items()},
        fx=m.fx_contribution(results["strategy"], results["strategy"]),
        figures={
            k: tmp_path / f"{k}.png"
            for k in ["equity", "underwater", "rolling_sharpe", "rolling_beta", "weights", "gate"]
        },
        figure_root=tmp_path,
    )
    assert report.render_report(**kwargs) == report.render_report(**kwargs)
