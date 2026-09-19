"""Small markdown-table helpers (no `tabulate` dependency)."""

from __future__ import annotations

import math

import pandas as pd


def fmt_pct(x: float, digits: int = 1) -> str:
    return (
        "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{digits}f}%"
    )


def fmt_num(x: float, digits: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{digits}f}"


def fmt_int(x: float) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{int(x):,}"


def fmt_date(x) -> str:
    return "n/a" if x is None or pd.isna(x) else pd.Timestamp(x).strftime("%Y-%m-%d")


def markdown_table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    align = align or ("l" + "r" * (len(headers) - 1))
    sep = ["---" if a == "l" else "---:" for a in align]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(sep) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# (label, metric key, formatter) in display order for the headline metrics table.
METRIC_ROWS: list[tuple[str, str, object]] = [
    ("Total return", "total_return", fmt_pct),
    ("CAGR", "cagr", fmt_pct),
    ("Annualized volatility", "ann_vol", fmt_pct),
    ("Sharpe (excess over DTB3)", "sharpe", fmt_num),
    ("Sortino (MAR 0)", "sortino", fmt_num),
    ("Max drawdown", "max_drawdown", fmt_pct),
    ("Max DD peak", "max_drawdown_peak", fmt_date),
    ("Max DD trough", "max_drawdown_trough", fmt_date),
    ("Max DD recovery", "max_drawdown_recovery", fmt_date),
    ("Max DD duration (days)", "max_drawdown_duration_days", fmt_int),
    ("Calmar", "calmar", fmt_num),
    ("Alpha vs S&P 500 (ann.)", "alpha_ann", fmt_pct),
    ("Beta vs S&P 500", "beta", fmt_num),
    ("Historical VaR 95% (daily)", "var_hist_95", fmt_pct),
    ("Historical VaR 99% (daily)", "var_hist_99", fmt_pct),
    ("Parametric VaR 95% (daily)", "var_param_95", fmt_pct),
    ("Parametric VaR 99% (daily)", "var_param_99", fmt_pct),
    ("CVaR / ES 95% (daily)", "cvar_95", fmt_pct),
    ("Excess kurtosis (daily)", "excess_kurtosis", fmt_num),
    ("Hit rate (weekly periods)", "hit_rate", fmt_pct),
    ("Average win (weekly period)", "avg_win", fmt_pct),
    ("Average loss (weekly period)", "avg_loss", fmt_pct),
    ("Annualized turnover", "ann_turnover", fmt_num),
    ("Total costs paid", "total_costs", fmt_num),
    ("Costs as % of final equity", "costs_pct_final_equity", lambda x: fmt_pct(x, 2)),
]


# Rows that only make sense over a multi-year window; suppressed in reports on short windows.
ANNUALISED_KEYS = {"cagr", "calmar", "alpha_ann"}
# Rows that compare against the S&P 500; they belong in the market-context appendix, not in the
# headline overlay-vs-buy-and-hold table.
MARKET_RELATIVE_KEYS = {"alpha_ann", "beta"}


def metrics_table(
    metrics: dict[str, dict],
    labels: dict[str, str],
    order: list[str],
    exclude: set[str] = frozenset(),
    suppress: set[str] = frozenset(),
    suppressed_text: str = "n/a",
) -> str:
    """Markdown table of ``METRIC_ROWS`` (minus ``exclude``) for the runs in ``order``; rows in
    ``suppress`` print ``suppressed_text`` instead of a value."""
    headers = ["Metric", *[labels.get(n, n) for n in order]]
    rows = []
    for label, key, fmt in METRIC_ROWS:
        if key in exclude:
            continue
        if key in suppress:
            rows.append([label, *[suppressed_text for _ in order]])
        else:
            rows.append([label, *[fmt(metrics[n].get(key)) for n in order]])  # type: ignore[operator]
    return markdown_table(headers, rows)


def drawdown_markdown(table: pd.DataFrame) -> str:
    rows = [
        [
            fmt_pct(r["depth"]),
            fmt_date(r["peak"]),
            fmt_date(r["trough"]),
            fmt_date(r["recovery"]) if pd.notna(r["recovery"]) else "not recovered",
            fmt_int(r["duration_days"]),
        ]
        for _, r in table.iterrows()
    ]
    return markdown_table(["Depth", "Peak", "Trough", "Recovery", "Duration (days)"], rows)
