"""Generate ``outputs/<run>/report.md`` (SPEC §1F).

Deterministic: no wall-clock timestamps and no git hash (the hash is logged to stdout by the CLI
instead, so the committed report does not change with every commit).

Voice: third person, present tense, every performance statement relative to equal-weight
buy-and-hold of the same basket and the window it was measured over. Verdict sentences are
generated from the numbers, never hard-coded; annualised figures are suppressed on windows
shorter than ``risk.metrics.MIN_ANNUALISE_SESSIONS``.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import pandas as pd

from thematic_alpha.config import Config
from thematic_alpha.reporting.tables import (
    ANNUALISED_KEYS,
    MARKET_RELATIVE_KEYS,
    drawdown_markdown,
    fmt_date,
    fmt_num,
    fmt_pct,
    markdown_table,
    metrics_table,
)
from thematic_alpha.risk.metrics import annualisable

LABELS = {
    "strategy": "Overlay",
    "sp500": "S&P 500 (SPY) buy-and-hold",
    "equal_weight_bh": "Equal-weight buy-and-hold (basket)",
    "naive_momentum": "Naive momentum (top-N)",
}
ORDER = ["strategy", "sp500", "equal_weight_bh", "naive_momentum"]
HEADLINE_ORDER = ["strategy", "equal_weight_bh"]
HIGH_BETA = 1.5  # above this the excess return over the index is read as market exposure
T_SIGNIFICANT = 2.0


def owned_portfolio_paragraph(universe: dict | None, config: Config) -> str:
    names = f"{universe['n_names']} names" if universe else "names"
    return (
        f"**What is being tested.** The {names} in `{config.universe.file}` are the author's own "
        "holdings. The basket is a given, not a selection result, so the question is not whether "
        "these names were a good pick but whether an active, macro-aware overlay beats simply "
        "holding them. Equal-weight buy-and-hold of the same basket is therefore the only "
        "benchmark that matters, and every overlay figure below is read against that column. "
        "Absolute returns carry the basket's own selection and say nothing about the rules; the "
        "S&P 500 appears in the appendix as context only."
    )


def point_in_time_paragraph(universe: dict, config: Config) -> str:
    seg = ", ".join(f"{n} {k}" for k, n in universe["segments"].items())
    liquidity = (
        f" and a 21-day average traded value of at least "
        f"{config.data.min_dollar_volume_21d:,.0f} {config.run.base_currency}"
        if config.data.min_dollar_volume_21d > 0
        else ""
    )
    return (
        f"**Control universe (point-in-time).** This run is the generalisation check for the "
        f"overlay, not the headline: a fixed list of {universe['n_names']} exchange-traded funds "
        f"chosen by category ({seg}), not by past performance, from `{universe['file']}`. A name "
        f"enters the cross-section only once it has {config.data.min_history_days} observed "
        f"sessions{liquidity}, so the investable set on every signal date is defined from data "
        "available on that date (composition table and figure below). If the overlay adds value "
        "on the author's basket but not here, the basket rather than the rules is the source. "
        "Residual bias: the list holds only funds that still trade at the snapshot date; funds "
        "in these categories that were liquidated or merged away are absent, which flatters "
        "buy-and-hold of the control basket (ETF-delisting bias). It is much smaller than "
        "hindsight stock selection, but it is not zero."
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
    cadence = f"evaluated {g.evaluation}"
    if not g.enabled:
        return f"disabled ({triggers})"
    if g.action == "scale":
        return (
            f"scale: {triggers} → ×{g.vix_scale_factor:g} / ×{g.yield_scale_factor:g} / "
            f"×{g.oil_scale_factor:g}; floor {g.min_exposure:g}; {g.combination}; {cadence}"
        )
    exempt = ", ".join(g.block_exempt_segments) or "none"
    return (
        f"block increases while any sub-gate is engaged ({triggers}); exempt segments: {exempt}; "
        f"scale factors and floor unused; {cadence}"
    )


def _finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _cmp(a: float, b: float, higher: str = "higher", lower: str = "lower") -> str:
    return higher if a > b else lower


def _months(n) -> str:
    """'an 8-month' / 'a 19-month' (article by pronunciation of the leading digits)."""
    text = str(n)
    an = text.startswith("8") or text in {"11", "18"} or text.startswith("11")
    return f"{'an' if an else 'a'} {text}-month"


def _verdict(metrics: dict[str, dict], config: Config) -> str:
    """One paragraph, generated from the numbers: overlay vs equal-weight buy-and-hold."""
    s, ew = metrics["strategy"], metrics["equal_weight_bh"]
    ann = annualisable(s)
    months = s.get("window_months")
    window = f"{config.run.start_date} → {config.run.end_date or 'latest data'}"
    ret_key, ret_label = ("cagr", "CAGR") if ann else ("total_return", "total return")
    better_ret = s[ret_key] > ew[ret_key]
    better_sharpe = s["sharpe"] > ew["sharpe"]
    shallower_dd = s["max_drawdown"] > ew["max_drawdown"]
    parts = [
        f"Over {window}"
        + (f" ({months} months)" if months is not None else "")
        + f" the overlay's {ret_label} is {_cmp(s[ret_key], ew[ret_key])} than equal-weight "
        f"buy-and-hold of the same basket ({fmt_pct(s[ret_key])} vs {fmt_pct(ew[ret_key])}), "
        f"its Sharpe is {_cmp(s['sharpe'], ew['sharpe'])} ({fmt_num(s['sharpe'])} vs "
        f"{fmt_num(ew['sharpe'])}), and its maximum drawdown is "
        f"{_cmp(s['max_drawdown'], ew['max_drawdown'], 'shallower', 'deeper')} "
        f"({fmt_pct(s['max_drawdown'])} vs {fmt_pct(ew['max_drawdown'])})."
    ]
    if _finite(s.get("beta")) and _finite(ew.get("beta")):
        parts.append(
            f"Realised beta to the S&P 500 is {fmt_num(s['beta'])} for the overlay and "
            f"{fmt_num(ew['beta'])} for buy-and-hold"
            + (
                ", so the extra return comes with more market exposure, not less."
                if better_ret and s["beta"] > ew["beta"]
                else "."
            )
        )
    if not (better_ret or better_sharpe or shallower_dd):
        parts.append("**The overlay does not add value over holding the basket**, net of costs.")
    elif better_ret and better_sharpe and shallower_dd:
        parts.append(
            "**The overlay adds value on return, risk-adjusted return and drawdown**, net of costs."
        )
    elif better_ret and better_sharpe:
        parts.append(
            "**The overlay adds return and risk-adjusted return, at the cost of a deeper "
            "drawdown**, net of costs."
        )
    elif better_ret:
        parts.append(
            "**The overlay adds return but not risk-adjusted value**: the extra return comes with "
            "a lower Sharpe"
            + (" and a deeper drawdown" if not shallower_dd else "")
            + ", net of costs."
        )
    else:
        gains = [
            g
            for g, ok in (
                ("a higher Sharpe", better_sharpe),
                ("a shallower drawdown", shallower_dd),
            )
            if ok
        ]
        parts.append(
            "**The overlay is roughly break-even to modestly value-additive on a risk-adjusted "
            "basis**: it gives up return relative to holding the basket in exchange for "
            + " and ".join(gains)
            + ", net of costs."
        )
    if not ann:
        parts.append(
            f"Annualised figures are omitted: {_months(months)} window is under the 24 months "
            "this report requires, and it is too short to conclude either way."
        )
    return " ".join(parts)


def _alpha_sentence(metrics: dict[str, dict]) -> str:
    sm = metrics["strategy"]
    a, b, t = sm.get("alpha_ann"), sm.get("beta"), sm.get("alpha_tstat")
    if not (_finite(a) and _finite(b)):
        return "Alpha and beta against the S&P 500 are not available for this run."
    if annualisable(sm):
        text = (
            f"Against the S&P 500 the overlay's annualised alpha is {fmt_pct(a)} at a beta of "
            f"{fmt_num(b)} (t = {fmt_num(t)})."
        )
    else:
        text = (
            f"Against the S&P 500 the overlay's beta is {fmt_num(b)}; alpha is not annualised "
            f"over {_months(sm.get('window_months'))} window (daily-alpha t = {fmt_num(t)})."
        )
    if b > HIGH_BETA:
        text += (
            f" At a beta above {HIGH_BETA:g} the excess return over the index is dominated by "
            "market exposure, not by selection."
        )
    if _finite(t):
        text += (
            " The alpha estimate is not distinguishable from zero at conventional levels."
            if abs(t) < T_SIGNIFICANT
            else " The alpha estimate is distinguishable from zero at conventional levels."
        )
    return text


def limitations(config: Config, universe: dict | None, metrics: dict[str, dict]) -> list[str]:
    sm = metrics["strategy"]
    months = sm.get("window_months")
    items: list[str] = []
    if config.universe.selection == "owned_portfolio":
        n = f"{universe['n_names']} " if universe else ""
        items.append(
            f"**Single personal basket.** The {n}names are one investor's holdings; the result is "
            "a statement about this basket and these rules, not about AI stocks or momentum "
            "overlays in general. The point-in-time ETF run is the only generalisation check."
        )
    else:
        items.append(
            "**ETF-delisting bias.** The control lists only funds that still trade at the "
            "snapshot date; liquidated or merged funds in the same categories are absent, which "
            "flatters buy-and-hold of the control basket."
        )
    items.append(
        f"**Flat slippage.** Costs are {config.costs.bps_per_side:g} bps per side plus "
        f"{config.costs.slippage_bps:g} bps slippage on every name regardless of size, which is "
        "optimistic for the smaller names and for re-entries after a gate release."
    )
    if months is not None and not annualisable(sm):
        items.append(
            f"**Short window.** {months} months of data; annualised statistics are suppressed "
            "and no verdict on the overlay can be drawn from this run alone."
        )
    items.append(
        "**No walk-forward.** Every parameter was set from standard practice and preregistered "
        "before the run, but there is no out-of-sample split; the ablation and sensitivity sets "
        "in `outputs/study.md` are the only robustness evidence."
    )
    items.append(
        "**Latest-revision macro data.** FRED series carry a one-session publication lag but "
        "are the current revision, not the vintage available on the day."
    )
    items.append(
        "**Next steps.** The 2026 case study against the real trade log, a point-in-time stock "
        "universe, and an out-of-sample split once the live window is long enough to support one."
    )
    return items


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
    universe_summary: dict | None = None,
) -> str:
    ccy = config.run.base_currency
    rc = config.report
    sm = metrics["strategy"]
    ann = annualisable(sm)
    suppress = set() if ann else ANNUALISED_KEYS
    suppressed_text = f"n/a ({sm.get('window_months')}-month window)"
    lines: list[str] = []

    # --- header: identity, thesis, framing, disclaimer -----------------------------------
    lines += [f"# {rc.title} — run `{config.run.name}`", ""]
    if rc.subtitle:
        lines += [f"*{rc.subtitle}*", ""]
    if rc.author:
        lines += [f"Author: {rc.author}", ""]
    if rc.thesis:
        lines += [f"**Thesis.** {rc.thesis}", ""]
    if config.universe.selection == "point_in_time" and universe_summary is not None:
        lines += [point_in_time_paragraph(universe_summary, config), ""]
    else:
        lines += [owned_portfolio_paragraph(universe_summary, config), ""]
    if rc.disclaimer:
        lines += [f"> {rc.disclaimer}", ""]

    # --- verdict --------------------------------------------------------------------------
    lines += ["## Verdict", "", _verdict(metrics, config), ""]

    # --- headline: overlay vs buy-and-hold of the basket ------------------------------------
    lines += ["## Headline results (net of costs): overlay vs buy-and-hold of the basket", ""]
    lines += [f"![equity curves]({figures['equity'].relative_to(figure_root).as_posix()})", ""]
    lines += [
        metrics_table(
            metrics,
            LABELS,
            HEADLINE_ORDER,
            exclude=MARKET_RELATIVE_KEYS,
            suppress=suppress,
            suppressed_text=suppressed_text,
        ),
        "",
    ]
    if not ann:
        lines += [
            f"Annualised rows (CAGR, Calmar, alpha) are not reported: the window covers "
            f"{sm.get('window_months')} months and the report annualises only over 24 or more.",
            "",
        ]
    lines += [
        f"VaR note: parametric (normal) 99% VaR of the overlay is {fmt_pct(sm['var_param_99'])} "
        f"against a historical {fmt_pct(sm['var_hist_99'])}; daily excess kurtosis is "
        f"{fmt_num(sm['excess_kurtosis'])}. "
        + (
            "The normal assumption understates the tail."
            if sm["var_param_99"] < sm["var_hist_99"]
            else "The normal assumption does not understate the 99% tail here."
        ),
        "",
    ]

    # --- config ---------------------------------------------------------------------------
    lines += ["## Configuration", ""]
    cfg_rows = [
        ["Backtest window", f"{config.run.start_date} → {config.run.end_date or 'latest data'}"],
        [
            "Universe",
            f"`{config.universe.file}`"
            + (f", {universe_summary['n_names']} names" if universe_summary else "")
            + f", selection: {config.universe.selection}; market: "
            f"{config.universe.benchmarks[0]}",
        ],
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
            "Idle cash",
            (
                f"earns {config.risk.rf_series} (calendar-day accrual), all runs"
                if config.backtest.cash_earns_rf
                else "earns 0"
            ),
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
            (
                f"block new exposure {config.event_mask.block_days_before_earnings} sessions "
                "before earnings (on)"
                if config.event_mask.enabled
                else "disabled"
            ),
        ],
        [
            "Sizing",
            f"max weight {config.sizing.max_position_weight:g}, cash floor "
            f"{config.sizing.cash_floor:g}",
        ],
        [
            "Liquidity screen",
            (
                f"21-day average traded value ≥ {config.data.min_dollar_volume_21d:,.0f} {ccy}"
                if config.data.min_dollar_volume_21d > 0
                else "off"
            ),
        ],
        [
            "Turnover control",
            f"position no-trade band {100 * config.turnover.position_band:g} pp "
            f"({'on' if config.turnover.position_band > 0 else 'off'}; overlay only)",
        ],
        ["Min history", f"{config.data.min_history_days} sessions"],
        ["Macro publication lag", f"{config.data.macro_publication_lag_days} session"],
    ]
    lines += [markdown_table(["Setting", "Value"], cfg_rows, align="ll"), ""]

    # --- data quality -----------------------------------------------------------------------
    lines += ["## Data quality", ""]
    q = quality_summary
    multi_calendar = len(q.get("mics", ["XNYS"])) > 1
    lines += [
        f"{q['n_tickers']} price series and {q['n_macro']} FRED series loaded; "
        f"{q['n_flagged']} single-day moves above {fmt_pct(q['threshold'], 0)} flagged for "
        f"manual review. Full per-ticker table: `data_quality.md` next to this report. "
        + (
            "Known handling: SK Hynix truncated to 2003 (mis-adjusted 2002 reverse split in the "
            "source), zero-volume bars on Korean holidays dropped, master calendar = NYSE ∪ KRX "
            "sessions with forward-fill only across a name's own holidays."
            if multi_calendar
            else "All names trade on US venues, so the master calendar is the NYSE session "
            "calendar; no cross-exchange alignment was needed."
        ),
        "",
    ]

    # --- universe composition -------------------------------------------------------------
    if universe_summary is not None and universe_summary.get("first_dates") is not None:
        fd = universe_summary["first_dates"]
        start = universe_summary["start"]
        lines += ["## Universe composition", ""]
        lines += [
            f"When each name enters the cross-section (backtest starts {fmt_date(start)}; a "
            "date before that means the name was eligible from the first signal date). "
            "Liquidity-eligible is the first date the 21-day average traded value clears the "
            "screen"
            + (
                "; the screen is off, so it equals the first price date."
                if config.data.min_dollar_volume_21d <= 0
                else "."
            ),
            "",
        ]
        rows = [
            [
                str(t),
                fmt_date(r["first_price"]),
                fmt_date(r["first_history_eligible"]),
                fmt_date(r["first_liquidity_eligible"]),
                fmt_date(r["first_eligible"]),
                (
                    "from start"
                    if pd.notna(r["first_eligible"]) and r["first_eligible"] <= start
                    else ("never" if pd.isna(r["first_eligible"]) else "mid-window")
                ),
            ]
            for t, r in fd.iterrows()
        ]
        lines += [
            markdown_table(
                [
                    "Ticker",
                    "First price",
                    "History-eligible",
                    "Liquidity-eligible",
                    "First eligible",
                    "Enters",
                ],
                rows,
                align="llllll",
            ),
            "",
        ]
        if "universe" in figures:
            lines += [
                f"![universe composition]"
                f"({figures['universe'].relative_to(figure_root).as_posix()})",
                "",
            ]

    # --- overlay activity -------------------------------------------------------------------
    s = strategy_summary
    lines += ["## Overlay activity", ""]
    if s.get("gate_action", "scale") == "scale":
        gate_text = (
            f"Macro-gate exposure averages {fmt_num(s['exposure_mean'])} (minimum "
            f"{fmt_num(s['exposure_min'])}; below 1.0 on {s['n_gated']} signal dates)."
        )
    else:
        exempt = ", ".join(s.get("exempt", [])) or "none"
        gate_text = (
            f"Macro gate in **block-increases** mode: risk-off on {s['n_risk_off']} signal dates, "
            f"{s['gate_blocked']} increases or entries blocked (that weight stays in cash; "
            f"exempt names: {exempt}). The scale factors and `min_exposure` are unused in "
            "this mode."
        )
    if s.get("n_evaluated") is not None and s["n_evaluated"] < s["n_signal_dates"]:
        gate_text += (
            f" The gate is evaluated on {s['n_evaluated']} of the {s['n_signal_dates']} signal "
            f"dates ({config.macro_gate.evaluation}) and held constant in between; ranking "
            "stays weekly."
        )
    if config.event_mask.enabled:
        mask_text = (
            f"Event mask: **{s['entries_blocked']} entries blocked pre-earnings** "
            f"({s['masked_ticker_dates']} ticker-dates masked; "
            f"{s['n_failed_open']} tickers without earnings dates failed open)."
        )
    else:
        mask_text = "Event mask: **disabled** (ETFs report no earnings; nothing to mask)."
    lines += [f"{s['n_signal_dates']} signal dates. {gate_text} {mask_text}", ""]
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

    # --- turnover attribution -------------------------------------------------------------
    if turnover is not None:
        lines += ["## Turnover attribution", ""]
        lines += [
            "Annualized turnover split by cause (see `backtest/attribution.py`): **membership** "
            "(entries and exits), **drift** (re-trading a held name back to an unchanged target, "
            "including the residual of earlier skipped or cash-scaled trades), **gate** (the "
            "macro gate changing the book) and **reweight** (ranker, mask and cap effects on a "
            "held name). Causes sum to the annualized turnover in the headline table.",
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
            f"{fmt_pct(turnover['gate_share'])} of the overlay's turnover."
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
    lines += ["## FX decomposition (overlay)", ""]
    fx_rows = [
        ["Total return", fmt_pct(fx["total_return_base"]), fmt_pct(fx["total_return_local"])],
    ]
    if ann:
        fx_rows.append(["CAGR", fmt_pct(fx["cagr_base"]), fmt_pct(fx["cagr_local"])])
    lines += [markdown_table(["", f"In {ccy}", "In local currencies"], fx_rows), ""]
    lines += [
        (
            f"FX contribution: {fmt_pct(fx['fx_contribution_cagr'])} per year of CAGR; in total "
            if ann
            else "FX contribution: in total "
        )
        + f"the {ccy} result differs from the local-currency result by "
        f"{fmt_pct(fx['fx_contribution_total'])} of initial capital. Positions are unhedged "
        + (
            " and ".join(universe_summary["currencies"])
            if universe_summary and universe_summary.get("currencies")
            else "foreign-currency"
        )
        + f" exposure held by a {ccy} investor.",
        "",
    ]

    # --- drawdowns --------------------------------------------------------------------------
    lines += ["## Largest drawdowns", ""]
    for name in HEADLINE_ORDER:
        lines += [f"**{LABELS[name]}**", "", drawdown_markdown(drawdowns[name]), ""]

    # --- appendix: market context ---------------------------------------------------------
    lines += ["## Appendix: market context", ""]
    lines += [
        "The S&P 500 (SPY) and a naive top-N momentum rule (no gate, no mask, no rank buffer, "
        "same costs) are shown for context only; neither is the benchmark this study is about.",
        "",
        metrics_table(metrics, LABELS, ORDER, suppress=suppress, suppressed_text=suppressed_text),
        "",
        _alpha_sentence(metrics),
        "",
    ]

    # --- limitations ----------------------------------------------------------------------
    lines += ["## Limitations and next steps", ""]
    lines += [f"- {item}" for item in limitations(config, universe_summary, metrics)]
    lines += [""]

    # --- figures ----------------------------------------------------------------------------
    lines += ["## Figures", ""]
    for key, caption in [
        ("underwater", "Overlay underwater plot"),
        ("rolling_sharpe", "Rolling 12-month Sharpe (overlay)"),
        ("rolling_beta", "Rolling beta vs S&P 500 (overlay)"),
        ("weights", "Allocation over time"),
        ("gate", "Applied macro-gate state and VIX"),
    ]:
        lines += [f"![{caption}]({figures[key].relative_to(figure_root).as_posix()})", ""]
    return "\n".join(lines)


def write_report(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
