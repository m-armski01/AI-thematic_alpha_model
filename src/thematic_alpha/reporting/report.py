"""Generate ``outputs/report.md`` (SPEC §1F).

Deterministic: no wall-clock timestamps and no git hash (the hash is logged to stdout by the CLI
instead, so the committed report does not change with every commit).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

from thematic_alpha.config import Config
from thematic_alpha.reporting.tables import (
    drawdown_markdown,
    fmt_num,
    fmt_pct,
    markdown_table,
    metrics_table,
)

LABELS = {
    "strategy": "Strategy",
    "sp500": "S&P 500 (SPY) B&H",
    "equal_weight_bh": "Equal-weight B&H (universe)",
    "naive_momentum": "Naive momentum (top-N)",
}
ORDER = ["strategy", "sp500", "equal_weight_bh", "naive_momentum"]

HINDSIGHT = (
    "**Hindsight bias, stated up front.** The universe was chosen in 2026 knowing which AI names "
    "had performed well. Every absolute return figure below is inflated by that selection and "
    "is **not** achievable ex-ante. The equal-weight buy-and-hold of the *same* basket is the "
    "benchmark that isolates what the rules add on top of the selection; read the strategy "
    "column against that one, not against the S&P 500."
)


def git_hash(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _gate_config_text(config: Config) -> str:
    g = config.macro_gate

    def _band(engage: float, name: str, fmt) -> str:
        release = g.release_threshold(name)
        return fmt(engage) if release == engage else f"{fmt(engage)} (release {fmt(release)})"

    triggers = (
        f"VIX>{_band(g.vix_threshold, 'vix', lambda v: f'{v:g}')}; "
        f"10y +{_band(g.yield_change_threshold, 'yield', lambda v: f'{100 * v:.0f}bp')}/"
        f"{g.yield_change_window}d; "
        f"WTI +{_band(g.oil_change_threshold, 'oil', lambda v: f'{100 * v:.0f}%')}/"
        f"{g.oil_change_window}d"
    )
    if not g.enabled:
        return f"disabled ({triggers})"
    if g.action == "scale":
        return (
            f"scale: {triggers} → ×{g.vix_scale_factor:g} / ×{g.yield_scale_factor:g} / "
            f"×{g.oil_scale_factor:g}; floor {g.min_exposure:g}; {g.combination}"
        )
    exempt = ", ".join(g.block_exempt_segments) or "none"
    return (
        f"block increases while any sub-gate is engaged ({triggers}); exempt segments: {exempt}; "
        "scale factors and floor unused"
    )


def _verdict(metrics: dict[str, dict]) -> str:
    s, ew = metrics["strategy"], metrics["equal_weight_bh"]
    better_sharpe = s["sharpe"] > ew["sharpe"]
    better_cagr = s["cagr"] > ew["cagr"]
    shallower_dd = s["max_drawdown"] > ew["max_drawdown"]
    parts = [
        f"Against equal-weight buy-and-hold of the same basket the strategy's CAGR is "
        f"{'higher' if better_cagr else 'lower'} ({fmt_pct(s['cagr'])} vs {fmt_pct(ew['cagr'])}), "
        f"its Sharpe is {'higher' if better_sharpe else 'lower'} "
        f"({fmt_num(s['sharpe'])} vs {fmt_num(ew['sharpe'])}), and its maximum drawdown is "
        f"{'shallower' if shallower_dd else 'deeper'} "
        f"({fmt_pct(s['max_drawdown'])} vs {fmt_pct(ew['max_drawdown'])})."
    ]
    if not (better_sharpe or better_cagr or shallower_dd):
        parts.append(
            "**This is an underperformance result**: the rules did not add value over simply "
            "holding the (hindsight-selected) basket, net of costs."
        )
    elif not better_cagr:
        parts.append(
            "The rules gave up total return relative to holding the basket"
            + (
                " in exchange for a better risk-adjusted profile."
                if better_sharpe or shallower_dd
                else "."
            )
        )
    return " ".join(parts)


def render_report(
    *,
    config: Config,
    quality_summary: dict,
    strategy_summary: dict,
    metrics: dict[str, dict],
    drawdowns: dict[str, pd.DataFrame],
    fx: dict,
    figures: dict[str, Path],
    figure_root: Path,
    turnover: dict | None = None,
) -> str:
    ccy = config.run.base_currency
    lines: list[str] = []
    lines += [f"# thematic-alpha report — run `{config.run.name}`", ""]
    lines += [HINDSIGHT, ""]
    lines += [
        "> Research system, not a trading system. Nothing here is investment advice. "
        "All figures are net of transaction costs.",
        "",
    ]

    # --- config ---------------------------------------------------------------------------
    lines += ["## Configuration", ""]
    cfg_rows = [
        ["Backtest window", f"{config.run.start_date} → {config.run.end_date or 'latest data'}"],
        ["Base currency", ccy],
        ["Rebalance", f"{config.backtest.rebalance}, {config.backtest.rebalance_day}"],
        [
            "Execution",
            f"t + {config.backtest.execution_lag_days} session at the "
            f"{config.backtest.execution_price}",
        ],
        [
            "Costs",
            f"model={config.costs.model}, {config.costs.bps_per_side:g} bps/side + "
            f"{config.costs.slippage_bps:g} bps slippage, flat {config.costs.flat_fee:g} {ccy}",
        ],
        [
            "Ranker",
            f"{config.ranker.method}, top {config.ranker.top_n} (exit rank "
            f"{config.ranker.effective_exit_rank}), {config.ranker.weighting}"
            + (
                f" (τ={config.ranker.softmax_temperature:g})"
                if config.ranker.weighting == "softmax"
                else ""
            ),
        ],
        ["Macro gate", _gate_config_text(config)],
        [
            "Event mask",
            f"block new exposure {config.event_mask.block_days_before_earnings} sessions before "
            f"earnings ({'on' if config.event_mask.enabled else 'off'})",
        ],
        [
            "Sizing",
            f"max weight {config.sizing.max_position_weight:g}, cash floor "
            f"{config.sizing.cash_floor:g}; house-money rule: Layer 2 (not applied)",
        ],
        [
            "Turnover control",
            f"position no-trade band {100 * config.turnover.position_band:g} pp "
            f"({'on' if config.turnover.position_band > 0 else 'off'}; strategy only)",
        ],
        ["Min history", f"{config.data.min_history_days} sessions"],
        ["Macro publication lag", f"{config.data.macro_publication_lag_days} session"],
    ]
    lines += [markdown_table(["Setting", "Value"], cfg_rows, align="ll"), ""]

    # --- data quality -----------------------------------------------------------------------
    lines += ["## Data quality", ""]
    q = quality_summary
    lines += [
        f"{q['n_tickers']} price series and {q['n_macro']} FRED series loaded; "
        f"{q['n_flagged']} single-day moves above {fmt_pct(q['threshold'], 0)} flagged for "
        f"manual review. Full per-ticker table: `outputs/data_quality.md`. Known handling: "
        "SK Hynix truncated to 2003 (mis-adjusted 2002 reverse split in the source), zero-volume "
        "bars on Korean holidays dropped, master calendar = NYSE ∪ KRX sessions with forward-fill "
        "only across a name's own holidays.",
        "",
    ]

    # --- strategy summary ---------------------------------------------------------------------
    s = strategy_summary
    lines += ["## Strategy activity", ""]
    if s.get("gate_action", "scale") == "scale":
        gate_text = (
            f"Macro-gate exposure averaged {fmt_num(s['exposure_mean'])} (minimum "
            f"{fmt_num(s['exposure_min'])}; below 1.0 on {s['n_gated']} signal dates)."
        )
    else:
        exempt = ", ".join(s.get("exempt", [])) or "none"
        gate_text = (
            f"Macro gate in **block-increases** mode: risk-off on {s['n_risk_off']} signal dates, "
            f"{s['gate_blocked']} increases or entries blocked (that weight stayed in cash; "
            f"exempt names: {exempt}). The scale factors and `min_exposure` are unused in "
            "this mode."
        )
    lines += [
        f"{s['n_signal_dates']} signal dates. {gate_text} Event mask: "
        f"**{s['entries_blocked']} entries blocked pre-earnings** "
        f"({s['masked_ticker_dates']} ticker-dates masked; "
        f"{s['n_failed_open']} tickers without earnings dates failed open).",
        "",
    ]
    if "held_rank_mean" in s:
        lines += [
            f"Average cross-sectional rank of the held names: **{fmt_num(s['held_rank_mean'])}** "
            f"(exit rank {s['exit_rank']}, top {config.ranker.top_n}; plain "
            f"top-{config.ranker.top_n} gives {(config.ranker.top_n + 1) / 2:.1f} by "
            "construction). A higher value is the "
            "signal-quality cost of the rank buffer: it holds names the ranker would otherwise "
            "have replaced.",
            "",
        ]

    # --- headline metrics -------------------------------------------------------------------
    lines += ["## Headline results (net of costs)", ""]
    lines += [f"![equity curves]({figures['equity'].relative_to(figure_root).as_posix()})", ""]
    lines += [metrics_table(metrics, LABELS, ORDER), ""]
    lines += [_verdict(metrics), ""]
    sm = metrics["strategy"]
    lines += [
        f"VaR note: parametric (normal) 99% VaR is {fmt_pct(sm['var_param_99'])} against a "
        f"historical {fmt_pct(sm['var_hist_99'])}; daily excess kurtosis is "
        f"{fmt_num(sm['excess_kurtosis'])}. "
        + (
            "The normal assumption understates the tail."
            if sm["var_param_99"] < sm["var_hist_99"]
            else "The normal assumption does not understate the 99% tail here."
        ),
        "",
    ]

    # --- turnover attribution -------------------------------------------------------------
    if turnover is not None:
        lines += ["## Turnover attribution", ""]
        lines += [
            "Annualized turnover split by cause (see `backtest/attribution.py`): **membership** "
            "(entries and exits), **drift** (re-trading a held name back to an unchanged target, "
            "including the residual of earlier skipped or cash-scaled trades), **gate** (the "
            "macro gate changing the book) and **reweight** (ranker, mask and cap effects on a "
            "held name). Causes sum to the annualized turnover in the table above.",
            "",
        ]
        causes = [c for c in next(iter(turnover["by_cause"].values())).index if c != "total"]
        rows = [
            [LABELS.get(n, n), *[fmt_num(float(s[c])) for c in causes], fmt_num(float(s["total"]))]
            for n, s in turnover["by_cause"].items()
        ]
        lines += [markdown_table(["Run", *causes, "total"], rows), ""]
        g = turnover["gate"]
        lines += [
            f"Macro gate: {g['n_transitions']} state transitions over {g['n_dates']} signal dates "
            f"({fmt_num(g['per_year'], 1)} per year); {g['reversed_within_1']} of them reverse "
            f"within 1 signal date and {g['reversed_within_2']} within 2. The gate accounts for "
            f"{fmt_pct(turnover['gate_share'])} of the strategy's turnover."
            + (
                " In block mode a blocked *entry* that executes after the release is membership "
                "turnover, not gate turnover, so this share only counts blocked increases of "
                "held names; with equal weights and a full book those are rare, and the gate's "
                "effect shows up as deferred membership and higher cash instead."
                if config.macro_gate.action == "block_increases"
                else ""
            ),
            "",
        ]
        if "turnover" in figures:
            lines += [
                f"![turnover by cause]({figures['turnover'].relative_to(figure_root).as_posix()})",
                "",
            ]

    # --- FX -------------------------------------------------------------------------------
    lines += ["## FX decomposition (strategy)", ""]
    fx_rows = [
        ["Total return", fmt_pct(fx["total_return_base"]), fmt_pct(fx["total_return_local"])],
        ["CAGR", fmt_pct(fx["cagr_base"]), fmt_pct(fx["cagr_local"])],
    ]
    lines += [markdown_table(["", f"In {ccy}", "In local currencies"], fx_rows), ""]
    lines += [
        f"FX contribution: {fmt_pct(fx['fx_contribution_cagr'])} per year of CAGR; in total the "
        f"{ccy} result differs from the local-currency result by "
        f"{fmt_pct(fx['fx_contribution_total'])} of initial capital. Positions are unhedged USD "
        f"and KRW exposure held by a {ccy} investor.",
        "",
    ]

    # --- drawdowns --------------------------------------------------------------------------
    lines += ["## Largest drawdowns", ""]
    for name in ("strategy", "equal_weight_bh"):
        lines += [f"**{LABELS[name]}**", "", drawdown_markdown(drawdowns[name]), ""]

    # --- figures ----------------------------------------------------------------------------
    lines += ["## Figures", ""]
    for key, caption in [
        ("underwater", "Strategy underwater plot"),
        ("rolling_sharpe", "Rolling 12-month Sharpe (strategy)"),
        ("rolling_beta", "Rolling beta vs S&P 500 (strategy)"),
        ("weights", "Allocation over time"),
        ("gate", "Applied macro-gate state and VIX"),
    ]:
        lines += [f"![{caption}]({figures[key].relative_to(figure_root).as_posix()})", ""]
    return "\n".join(lines)


def write_report(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
