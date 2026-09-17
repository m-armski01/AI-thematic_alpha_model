"""Study runner (brief v2, step 7): control rerun + ablation on every universe, one pass.

    python -m thematic_alpha.study --configs configs/etf.yaml configs/base.yaml [--refresh]

Data and features are loaded once per universe; benchmarks are run once per universe; then
only strategy + backtest + risk + attribution are rerun per variant. Variants are declared as
overrides on the chosen config (``L1``, ``KNOBS``, ``variants()``), never chosen after seeing
results; the
sensitivity rows are reported next to each other and nothing is promoted. Writes
``outputs/study.md`` and ``outputs/study/`` (tables as CSV, figures).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from thematic_alpha import pipeline
from thematic_alpha.backtest import attribution as attr
from thematic_alpha.backtest.engine import BacktestResult
from thematic_alpha.config import Config
from thematic_alpha.reporting import plots
from thematic_alpha.reporting.report import LABELS, git_hash
from thematic_alpha.reporting.tables import fmt_num, fmt_pct, markdown_table

logger = logging.getLogger("thematic_alpha.study")

# --- variant declarations ----------------------------------------------------------------

L1 = {
    "ranker": {"weighting": "conviction_tier", "exit_rank": None},
    "turnover": {"position_band": 0.0},
    "macro_gate": {
        "action": "scale",
        "vix_release_threshold": None,
        "yield_release_threshold": None,
        "oil_release_threshold": None,
        "evaluation": "weekly",
    },
}

# Each knob as a (section, key, chosen-value) triple, in the cumulative order of the brief.
KNOBS: list[tuple[str, str, dict]] = [
    ("equal weight", "weighting", {"ranker": {"weighting": "equal"}}),
    ("hysteresis (exit rank 8)", "hysteresis", {"ranker": {"exit_rank": 8}}),
    ("position band 2pp", "band", {"turnover": {"position_band": 0.02}}),
    ("gate: block increases", "block", {"macro_gate": {"action": "block_increases"}}),
    (
        "gate: Schmitt trigger",
        "schmitt",
        {
            "macro_gate": {
                "vix_release_threshold": 20.0,
                "yield_release_threshold": 0.32,
                "oil_release_threshold": 0.16,
            }
        },
    ),
    ("gate: monthly evaluation", "monthly", {"macro_gate": {"evaluation": "monthly"}}),
]


CHOSEN_KEY = "cum_monthly"  # the last cumulative step equals the chosen config


@dataclass
class Variant:
    key: str
    label: str
    group: str  # baseline | cumulative | one_at_a_time | sensitivity | reference
    overrides: dict = field(default_factory=dict)  # applied on top of L1 (or chosen: see below)
    base: str = "L1"  # "L1" or "chosen"


def deep_merge(base: dict, overrides: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def variants() -> list[Variant]:
    out = [Variant("L1", "L1 baseline (tiers, top-N, no band, gate scale/weekly)", "baseline")]
    acc: dict = {}
    for label, key, ov in KNOBS:
        acc = deep_merge(acc, ov)
        out.append(Variant(f"cum_{key}", f"+ {label}", "cumulative", dict(acc)))
    out[-1].label += " (= chosen)"
    for label, key, ov in KNOBS:
        out.append(Variant(f"only_{key}", f"L1 + {label} only", "one_at_a_time", ov))
    for tau in (0.5, 1.0, 2.0):
        out.append(
            Variant(
                f"softmax_{tau:g}",
                f"chosen with softmax τ={tau:g}",
                "sensitivity",
                {"ranker": {"weighting": "softmax", "softmax_temperature": tau}},
                base="chosen",
            )
        )
    out.append(
        Variant(
            "no_gate",
            "chosen with the macro gate disabled",
            "reference",
            {"macro_gate": {"enabled": False}},
            base="chosen",
        )
    )
    out.append(
        Variant(
            "no_screen",
            "chosen with the liquidity screen off",
            "reference",
            {"data": {"min_dollar_volume_21d": 0.0}},
            base="chosen",
        )
    )
    return out


def variant_config(chosen: Config, v: Variant) -> Config:
    raw = chosen.model_dump()
    if v.base == "L1":
        raw = deep_merge(raw, L1)
    raw = deep_merge(raw, v.overrides)
    return Config.model_validate(raw)


# --- per-variant metrics -----------------------------------------------------------------


def effective_n(target_weights: pd.DataFrame) -> float:
    """Mean over signal dates of 1 / Σ (w/Σw)² (dates with nothing held excluded)."""
    total = target_weights.sum(axis=1)
    w = target_weights[total > 0].div(total[total > 0], axis=0)
    if w.empty:
        return float("nan")
    return float((1.0 / (w**2).sum(axis=1)).mean())


def average_cash(result: BacktestResult) -> float:
    return float((result.cash / result.equity_curve).mean())


def row_metrics(
    strategy: pipeline.StrategyBundle,
    result: BacktestResult,
    metrics: dict,
    attribution: pipeline.AttributionBundle,
) -> dict:
    bc = attribution.strategy
    return {
        "cagr": metrics["cagr"],
        "sharpe": metrics["sharpe"],
        "max_drawdown": metrics["max_drawdown"],
        "ann_turnover": metrics["ann_turnover"],
        **{f"turnover_{c}": float(bc[c]) for c in attr.CAUSES},
        "costs_pct_final_equity": metrics["costs_pct_final_equity"],
        "held_rank": float(strategy.held_rank.mean()),
        "gate_transitions_per_year": attribution.gate.per_year,
        "avg_cash": average_cash(result),
        "effective_n": effective_n(strategy.target_weights),
    }


@dataclass
class UniverseStudy:
    name: str
    config: Config
    bundle: pipeline.DataBundle
    benchmarks: dict[str, BacktestResult]
    benchmark_metrics: dict[str, dict]
    benchmark_attribution: dict[str, pd.Series]
    rows: pd.DataFrame  # variant x metrics
    by_cause: dict[str, pd.Series]  # variant key -> annualized turnover by cause
    first_dates: pd.DataFrame
    composition_figure: Path
    strategy_equity: pd.Series  # the chosen variant's equity curve
    chosen_key: str = "cum_monthly"


def run_universe(config: Config, root: Path, refresh: bool = False) -> UniverseStudy:
    t0 = time.perf_counter()
    bundle = pipeline.load_data(config, root, refresh=refresh)
    features_cache: dict[float, pipeline.FeaturePanel] = {}

    def features_for(cfg: Config) -> pipeline.FeaturePanel:
        key = cfg.data.min_dollar_volume_21d
        if key not in features_cache:
            features_cache[key] = pipeline.build_features(bundle, cfg)
        return features_cache[key]

    features = features_for(config)
    # Benchmarks once, under the chosen config (they depend on eligibility only).
    chosen_strategy = pipeline.build_strategy(bundle, features, config, root)
    all_results = pipeline.run_backtests(bundle, features, chosen_strategy, config)
    benchmarks = {n: all_results[n] for n in pipeline.BENCHMARK_ORDER}
    risk = pipeline.compute_risk(bundle, all_results, config)
    bench_attr = pipeline.attribute_turnover(chosen_strategy, all_results)
    logger.info(
        "%s: data + features + benchmarks in %.1fs", config.run.name, time.perf_counter() - t0
    )

    rows, by_cause = {}, {}
    strategy_equity = None
    for v in variants():
        cfg = variant_config(config, v)
        feats = features_for(cfg)
        strategy = pipeline.build_strategy(bundle, feats, cfg, root)
        results = pipeline.run_backtests(bundle, feats, strategy, cfg)
        vrisk = pipeline.compute_risk(bundle, results, cfg)
        vattr = pipeline.attribute_turnover(strategy, results)
        rows[v.key] = {
            "label": v.label,
            "group": v.group,
            **row_metrics(strategy, results[pipeline.STRATEGY], vrisk.metrics["strategy"], vattr),
        }
        by_cause[v.key] = vattr.strategy
        if v.key == CHOSEN_KEY:
            strategy_equity = results[pipeline.STRATEGY].equity_curve
        logger.info(
            "%s | %-45s CAGR %5.1f%% Sharpe %4.2f DD %6.1f%% turnover %5.2f held-rank %.2f",
            config.run.name,
            v.label,
            100 * rows[v.key]["cagr"],
            rows[v.key]["sharpe"],
            100 * rows[v.key]["max_drawdown"],
            rows[v.key]["ann_turnover"],
            rows[v.key]["held_rank"],
        )
    frame = pd.DataFrame.from_dict(rows, orient="index")
    frame.index.name = "variant"
    return UniverseStudy(
        name=config.run.name,
        config=config,
        bundle=bundle,
        benchmarks=benchmarks,
        benchmark_metrics={n: risk.metrics[n] for n in pipeline.BENCHMARK_ORDER},
        benchmark_attribution={n: bench_attr.by_cause[n] for n in pipeline.BENCHMARK_ORDER},
        rows=frame,
        by_cause=by_cause,
        first_dates=features.first_dates,
        composition_figure=pipeline.output_dir(root, config)
        / "figures"
        / "universe_composition.png",
        strategy_equity=strategy_equity,
        chosen_key=CHOSEN_KEY,
    )


# --- report ------------------------------------------------------------------------------


def check_comparable(configs: list[Config]) -> None:
    ref = configs[0]
    for c in configs[1:]:
        for label, a, b in (
            ("run.start_date", ref.run.start_date, c.run.start_date),
            ("run.end_date", ref.run.end_date, c.run.end_date),
            ("costs", ref.costs, c.costs),
            ("run.base_currency", ref.run.base_currency, c.run.base_currency),
            ("ranker.top_n", ref.ranker.top_n, c.ranker.top_n),
        ):
            if a != b:
                raise ValueError(f"configs differ in {label}: {a!r} vs {b!r}")
    if ref.run.end_date is None:
        raise ValueError("run.end_date must be pinned to the data snapshot date for the study")


def _cmp(a: float, b: float, higher: str = "higher", lower: str = "lower") -> str:
    return higher if a > b else lower


def headline_verdict(s: dict, ew: dict, spy: dict, nm: dict) -> str:
    beats_ew = s["sharpe"] > ew["sharpe"] or s["cagr"] > ew["cagr"]
    return (
        f"On the point-in-time ETF control the overlay's CAGR is {_cmp(s['cagr'], ew['cagr'])} "
        f"than equal-weight buy-and-hold of the same 17 ETFs ({fmt_pct(s['cagr'])} vs "
        f"{fmt_pct(ew['cagr'])}), its Sharpe is {_cmp(s['sharpe'], ew['sharpe'])} "
        f"({fmt_num(s['sharpe'])} vs {fmt_num(ew['sharpe'])}) and its maximum drawdown is "
        f"{_cmp(s['max_drawdown'], ew['max_drawdown'], 'shallower', 'deeper')} "
        f"({fmt_pct(s['max_drawdown'])} vs {fmt_pct(ew['max_drawdown'])}). Against SPY it is "
        f"{_cmp(s['cagr'], spy['cagr'])} on CAGR ({fmt_pct(spy['cagr'])}) and "
        f"{_cmp(s['sharpe'], spy['sharpe'])} on Sharpe ({fmt_num(spy['sharpe'])}); against naive "
        f"top-5 momentum it is {_cmp(s['sharpe'], nm['sharpe'])} on Sharpe "
        f"({fmt_num(nm['sharpe'])}). "
        + (
            "The overlay adds something on this universe."
            if beats_ew
            else "**The overlay does not beat holding the ETF basket**, net of costs."
        )
    )


def selection_verdict(stock: dict, etf: dict, stock_ew: dict, etf_ew: dict) -> str:
    d_cagr = stock["cagr"] - etf["cagr"]
    d_sharpe = stock["sharpe"] - etf["sharpe"]
    d_ew = stock_ew["cagr"] - etf_ew["cagr"]
    return (
        f"Same rules, same window, same costs: **{fmt_pct(stock['cagr'])} CAGR on the owned "
        f"basket, {fmt_pct(etf['cagr'])} on the ETF control** — a difference of "
        f"{fmt_pct(d_cagr)} per year and {fmt_num(d_sharpe)} of Sharpe "
        f"({fmt_num(stock['sharpe'])} vs {fmt_num(etf['sharpe'])}). The equal-weight "
        f"buy-and-hold shows the same gap without any rules: {fmt_pct(stock_ew['cagr'])} for the "
        f"12 stocks vs {fmt_pct(etf_ew['cagr'])} for the 17 ETFs ({fmt_pct(d_ew)} per year, "
        f"Sharpe {fmt_num(stock_ew['sharpe'])} vs {fmt_num(etf_ew['sharpe'])}). "
        + (
            "The basket, not the rules, is where the return came from."
            if abs(d_ew) > abs(d_cagr - d_ew)
            else "The rules interact with the universe: the gap between the two overlay runs is "
            "larger than the gap between the two buy-and-holds."
        )
    )


def turnover_verdict(
    name: str, before: pd.Series, after: pd.Series, hr_before: float, hr_after: float
) -> str:
    cut = 1 - after["total"] / before["total"] if before["total"] > 0 else 0.0
    return (
        f"{name}: annualized turnover {fmt_num(before['total'])}x → {fmt_num(after['total'])}x "
        f"({fmt_pct(cut, 0)} lower), average held rank {fmt_num(hr_before)} → {fmt_num(hr_after)} "
        f"(the signal-quality cost of the rank buffer: {fmt_num(hr_after - hr_before)} ranks)."
    )


def ablation_table(studies: list[UniverseStudy]) -> str:
    cols = [
        ("CAGR", "cagr", fmt_pct),
        ("Sharpe", "sharpe", fmt_num),
        ("Max DD", "max_drawdown", fmt_pct),
        ("Turnover", "ann_turnover", fmt_num),
        ("member.", "turnover_membership", fmt_num),
        ("drift", "turnover_drift", fmt_num),
        ("gate", "turnover_gate", fmt_num),
        ("reweight", "turnover_reweight", fmt_num),
        ("Costs %eq", "costs_pct_final_equity", lambda x: fmt_pct(x, 2)),
        ("Held rank", "held_rank", fmt_num),
        ("Gate tr./yr", "gate_transitions_per_year", lambda x: fmt_num(x, 1)),
        ("Avg cash", "avg_cash", lambda x: fmt_pct(x, 0)),
        ("Eff. N", "effective_n", lambda x: fmt_num(x, 1)),
    ]
    rows = []
    for st in studies:
        for _, r in st.rows.iterrows():
            rows.append([st.name, r["label"], *[fmt(r[k]) for _, k, fmt in cols]])
    return markdown_table(
        ["Universe", "Variant", *[c for c, _, _ in cols]], rows, align="ll" + "r" * len(cols)
    )


GATE_COMPARABILITY = (
    "**Gate comparability across universes.** TLT and GLD change what the gate is measuring. "
    "With defensive assets in the universe, risk-off rotation can happen through the ranker: "
    "momentum simply selects bonds or gold, and the gate never has to force cash. The two "
    "mechanisms partly substitute for each other, so the gate's measured contribution on the "
    "ETF universe (the block, Schmitt and monthly rows, and the gate-disabled reference) is "
    "**not directly comparable** to its contribution on the stock universe, where the gate is "
    "the only risk-off mechanism. The `defensive` segment is exempt from the block rule, which "
    "is exactly what lets that substitution happen while the gate is risk-off."
)


def render_study(studies: list[UniverseStudy], out_dir: Path, figures: dict[str, Path]) -> str:
    by_name = {s.name: s for s in studies}
    etf, stock = by_name.get("etf"), by_name.get("base")
    cfg = studies[0].config
    lines: list[str] = []
    lines += [
        "# thematic-alpha study — does the overlay generalise? ETF control and ablation",
        "",
    ]
    lines += [
        f"Data snapshot {cfg.run.end_date}; window {cfg.run.start_date} → {cfg.run.end_date}; "
        f"costs {cfg.costs.bps_per_side:g} bps/side + {cfg.costs.slippage_bps:g} bps slippage; "
        f"base currency {cfg.run.base_currency}; top {cfg.ranker.top_n}. All figures net of costs, "
        "annualized on the NYSE session calendar. Every parameter was *set from standard "
        "practice, not optimised* and committed before the run: "
        "[docs/preregistration_v2.md](../docs/preregistration_v2.md). Universes: "
        + ", ".join(
            f"`{s.config.universe.file}` ({len(s.bundle.universe.tickers)} names, {s.name})"
            for s in studies
        )
        + ".",
        "",
    ]

    # 1. ETF headline
    if etf is not None:
        lines += [
            "## 1. ETF control: overlay vs equal-weight buy-and-hold (ETF) vs SPY vs naive "
            "momentum",
            "",
        ]
        chosen = etf.rows.loc[etf.chosen_key]
        s = {
            "cagr": chosen["cagr"],
            "sharpe": chosen["sharpe"],
            "max_drawdown": chosen["max_drawdown"],
            "ann_turnover": chosen["ann_turnover"],
            "costs_pct_final_equity": chosen["costs_pct_final_equity"],
        }
        bm = etf.benchmark_metrics
        rows = [
            [
                "CAGR",
                fmt_pct(s["cagr"]),
                *[fmt_pct(bm[n]["cagr"]) for n in pipeline.BENCHMARK_ORDER],
            ],
            [
                "Sharpe",
                fmt_num(s["sharpe"]),
                *[fmt_num(bm[n]["sharpe"]) for n in pipeline.BENCHMARK_ORDER],
            ],
            [
                "Max drawdown",
                fmt_pct(s["max_drawdown"]),
                *[fmt_pct(bm[n]["max_drawdown"]) for n in pipeline.BENCHMARK_ORDER],
            ],
            [
                "Annualized turnover",
                fmt_num(s["ann_turnover"]),
                *[fmt_num(bm[n]["ann_turnover"]) for n in pipeline.BENCHMARK_ORDER],
            ],
            [
                "Costs (% of final equity)",
                fmt_pct(s["costs_pct_final_equity"], 2),
                *[fmt_pct(bm[n]["costs_pct_final_equity"], 2) for n in pipeline.BENCHMARK_ORDER],
            ],
        ]
        lines += [
            markdown_table(
                ["", "Overlay (chosen)", *[LABELS[n] for n in pipeline.BENCHMARK_ORDER]], rows
            ),
            "",
        ]
        lines += [headline_verdict(s, bm["equal_weight_bh"], bm["sp500"], bm["naive_momentum"]), ""]
        lines += [
            f"![ETF equity curves]({figures['etf_equity'].relative_to(out_dir.parent).as_posix()})",
            "",
        ]

    # 2. Selection bias
    if etf is not None and stock is not None:
        lines += [
            "## 2. Selection bias: identical chosen rules, the owned 12-stock basket vs the "
            "17-ETF control",
            "",
        ]
        sc, ec = stock.rows.loc[stock.chosen_key], etf.rows.loc[etf.chosen_key]
        sew, eew = (
            stock.benchmark_metrics["equal_weight_bh"],
            etf.benchmark_metrics["equal_weight_bh"],
        )
        rows = [
            [
                "Overlay (chosen rules) CAGR",
                fmt_pct(sc["cagr"]),
                fmt_pct(ec["cagr"]),
                fmt_pct(sc["cagr"] - ec["cagr"]),
            ],
            [
                "Overlay Sharpe",
                fmt_num(sc["sharpe"]),
                fmt_num(ec["sharpe"]),
                fmt_num(sc["sharpe"] - ec["sharpe"]),
            ],
            [
                "Overlay max drawdown",
                fmt_pct(sc["max_drawdown"]),
                fmt_pct(ec["max_drawdown"]),
                fmt_pct(sc["max_drawdown"] - ec["max_drawdown"]),
            ],
            [
                "Equal-weight buy-and-hold CAGR",
                fmt_pct(sew["cagr"]),
                fmt_pct(eew["cagr"]),
                fmt_pct(sew["cagr"] - eew["cagr"]),
            ],
            [
                "Equal-weight buy-and-hold Sharpe",
                fmt_num(sew["sharpe"]),
                fmt_num(eew["sharpe"]),
                fmt_num(sew["sharpe"] - eew["sharpe"]),
            ],
            [
                "SPY buy-and-hold CAGR (same in both)",
                fmt_pct(stock.benchmark_metrics["sp500"]["cagr"]),
                fmt_pct(etf.benchmark_metrics["sp500"]["cagr"]),
                "",
            ],
        ]
        lines += [
            markdown_table(
                ["", "12 stocks (owned basket)", "17 ETFs (point-in-time control)", "difference"],
                rows,
            ),
            "",
        ]
        lines += [selection_verdict(sc, ec, sew, eew), ""]

    # 3. Turnover decomposition
    lines += ["## 3. Turnover decomposition: L1 baseline vs chosen, both universes", ""]
    lines += [
        f"![turnover before/after]({figures['turnover'].relative_to(out_dir.parent).as_posix()})",
        "",
    ]
    rows = []
    for st in studies:
        for key in ("L1", st.chosen_key):
            r, bc = st.rows.loc[key], st.by_cause[key]
            rows.append(
                [
                    st.name,
                    "L1 baseline" if key == "L1" else "chosen",
                    *[fmt_num(bc[c]) for c in attr.CAUSES],
                    fmt_num(bc["total"]),
                    fmt_num(r["held_rank"]),
                    fmt_pct(r["costs_pct_final_equity"], 2),
                ]
            )
    lines += [
        markdown_table(
            ["Universe", "Rules", *attr.CAUSES, "total", "held rank", "costs %eq"],
            rows,
            align="ll" + "r" * 7,
        ),
        "",
    ]
    for st in studies:
        lines += [
            turnover_verdict(
                st.name,
                st.by_cause["L1"],
                st.by_cause[st.chosen_key],
                st.rows.loc["L1", "held_rank"],
                st.rows.loc[st.chosen_key, "held_rank"],
            ),
            "",
        ]
    lines += [
        "In block mode a blocked entry that executes after the release counts as membership, so "
        "the gate column understates the gate's effect there; the gate-disabled reference row "
        "in the ablation is the honest measure of what the gate does.",
        "",
    ]

    # 4. Ablation
    lines += ["## 4. Ablation", ""]
    lines += [
        "Rows are declared in `study.py` (`L1`, `KNOBS`, `variants()`): the L1 baseline, the "
        "cumulative chain in "
        "the brief's order, each knob alone on the baseline, the softmax sensitivity set on the "
        "chosen config, and two references (gate disabled; liquidity screen off). The "
        "liquidity screen is part of the universe definition and stays on in every other row; "
        "note that the screen also changes the equal-weight buy-and-hold (re-equalized on every "
        "eligibility change), so the screen-off row is not comparable to the benchmark table "
        "above. Nothing here was used to change a chosen value.",
        "",
    ]
    lines += [ablation_table(studies), ""]
    lines += [GATE_COMPARABILITY, ""]
    for st in studies:
        r = st.rows
        best_turnover = r.loc[r["group"] == "one_at_a_time", "ann_turnover"].idxmin()
        l1, ch = r.loc["L1"], r.loc[st.chosen_key]
        lines += [
            f"{st.name}: the single knob that cuts turnover most on its own is "
            f"*{r.loc[best_turnover, 'label']}* ({fmt_num(l1['ann_turnover'])}x → "
            f"{fmt_num(r.loc[best_turnover, 'ann_turnover'])}x). L1 → chosen: Sharpe "
            f"{fmt_num(l1['sharpe'])} → {fmt_num(ch['sharpe'])}, CAGR {fmt_pct(l1['cagr'])} → "
            f"{fmt_pct(ch['cagr'])}, max drawdown {fmt_pct(l1['max_drawdown'])} → "
            f"{fmt_pct(ch['max_drawdown'])}. Gate disabled: Sharpe "
            f"{fmt_num(r.loc['no_gate', 'sharpe'])}, so the gate "
            f"{'adds' if ch['sharpe'] > r.loc['no_gate', 'sharpe'] else 'subtracts'} "
            f"{fmt_num(abs(ch['sharpe'] - r.loc['no_gate', 'sharpe']))} of Sharpe on this "
            "universe. "
            f"Softmax τ ∈ {{0.5, 1, 2}}: Sharpe "
            + ", ".join(fmt_num(r.loc[f"softmax_{t:g}", "sharpe"]) for t in (0.5, 1.0, 2.0))
            + ", effective N "
            + ", ".join(fmt_num(r.loc[f"softmax_{t:g}", "effective_n"], 1) for t in (0.5, 1.0, 2.0))
            + f" (equal weight: {fmt_num(ch['effective_n'], 1)}).",
            "",
        ]

    # 5. Universe composition
    if etf is not None:
        lines += ["## 5. Universe composition over time (ETF universe)", ""]
        fd = etf.first_dates
        start = pd.Timestamp(cfg.run.start_date)
        mid = fd[fd["first_eligible"] > start]
        lines += [
            f"{len(fd)} names; {len(fd) - len(mid)} eligible from the first signal date, "
            + (
                ", ".join(f"{t} from {d.date()}" for t, d in mid["first_eligible"].items())
                if len(mid)
                else "none"
            )
            + " entering mid-window. Full table in `outputs/etf/report.md`.",
            "",
            "![universe composition]"
            f"({figures['composition'].relative_to(out_dir.parent).as_posix()})",
            "",
        ]
    return "\n".join(lines)


def make_study_figures(studies: list[UniverseStudy], out_dir: Path) -> dict[str, Path]:
    figs: dict[str, Path] = {}
    by_cause = {}
    labels = {}
    for st in studies:
        for key, tag in (("L1", "L1 baseline"), (st.chosen_key, "chosen")):
            name = f"{st.name}:{key}"
            by_cause[name] = st.by_cause[key]
            labels[name] = f"{st.name}\n{tag}"
    figs["turnover"] = plots.turnover_by_cause(
        by_cause, labels, attr.CAUSES, out_dir / "turnover_before_after.png"
    )
    etf = next((s for s in studies if s.name == "etf"), None)
    if etf is not None:
        curves = {n: etf.benchmarks[n].equity_curve for n in pipeline.BENCHMARK_ORDER}
        figs["etf_equity"] = plots.equity_curves(
            {"strategy": etf.strategy_equity, **curves}, LABELS, out_dir / "etf_equity_curves.png"
        )
        figs["composition"] = out_dir / "etf_universe_composition.png"
        shutil.copyfile(etf.composition_figure, figs["composition"])
    return figs


def run_study(config_paths: list[Path], refresh: bool = False) -> Path:
    configs = [Config.from_yaml(p) for p in config_paths]
    check_comparable(configs)
    root = config_paths[0].resolve().parent.parent
    logger.info("code version %s", git_hash(root))
    studies = [run_universe(c, root, refresh) for c in configs]
    out_dir = root / "outputs" / "study"
    out_dir.mkdir(parents=True, exist_ok=True)
    for st in studies:
        st.rows.round(6).to_csv(out_dir / f"ablation_{st.name}.csv")
    figures = make_study_figures(studies, out_dir)
    text = render_study(studies, out_dir, figures)
    path = root / "outputs" / "study.md"
    path.write_text(text)
    logger.info("study -> %s", path)
    return path


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        prog="thematic_alpha.study", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--configs", nargs="+", required=True, type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    path = run_study(args.configs, refresh=args.refresh)
    print(f"[study] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
