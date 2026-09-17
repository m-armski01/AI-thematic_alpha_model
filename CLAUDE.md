# thematic-alpha

Spec: `../AI sector quantbot SPEC.md`; brief v2 decisions are recorded in the task history and
`docs/preregistration_v2.md`; the publishable-state rework is the work order in `IMPROVEMENTS.md`.
Status and results: `README.md` → "Build status" and `outputs/study.md`. Layer 1 (12-stock
basket, PR #2), brief v2 (point-in-time ETF universe + turnover control, issue #3) and the
IMPROVEMENTS rework (cash at DTB3, report reframing, regimes, momentum-window sensitivity,
scaffolding removal; branch `4-publishable-report`, issue #4) are done. Next: the §13 case study
(2026 YTD vs the real trade log), a point-in-time stock universe (§15).

**Framing.** This is a single-investor study: the 12 names in `data/reference/universe.csv` are
the author's holdings (`universe.selection: owned_portfolio`), the headline is the overlay vs
equal-weight buy-and-hold of that basket, and the ETF universe (`point_in_time`) and the study
are the generalisation control. The `report:` block in each YAML fixes title / subtitle / author
/ thesis; every verdict sentence is generated from the numbers.

## Environment and commands

- Interpreter: `.venv/bin/python` (3.12) in this directory. This directory is the GitHub repo; the
  sibling `../thematic-alpha/` folder is a dead Layer-0 copy — ignore it.
- One run: `python -m thematic_alpha.run --config configs/etf.yaml` (headline) or
  `configs/base.yaml` (control) → `outputs/<run.name>/` (`--refresh` forces re-download;
  `--layer 0` is the NVDA smoke test).
- The study: `python -m thematic_alpha.study --configs configs/etf.yaml configs/base.yaml` →
  `outputs/study.md` + `outputs/study/`. ~30 s from the cache.
- Tests: `pytest` — fully offline, synthetic markets in `tests/synthetic.py` (two-ticker and the
  12-ticker wide market), golden fixture in `tests/fixtures/`.
- Lint: `ruff check . && black --check .` (line length 100).
- Both configs pin `run.end_date: 2026-09-11` (the data snapshot) and `max_cache_age_days: 30` so
  the cache is served; the yfinance fetch end is made inclusive in `pipeline.load_data`.

## Rules

- Keep the checkpoint rhythm: one sub-step → lint, tests, real demo run, one commit.
- **Neutral defaults.** Every new config knob's pydantic default reproduces Layer 1 exactly;
  chosen values live only in the YAML configs. `tests/test_golden.py` must stay green; extend
  `LAYER1_NEUTRAL` and `CHOSEN` in `tests/synthetic.py` whenever a knob is added. Current
  knobs beyond Layer 1: `backtest.cash_earns_rf` (idle cash at DTB3, calendar-day accrual, on
  in all configs as a measurement change) and `ranker.momentum_signal` (mom_63 chosen;
  mom_126 / mom_252 are a sensitivity set in the study, nothing promoted).
- **Parameter discipline.** Values go into `docs/preregistration_v2.md` (neutral, chosen,
  rationale, "set from standard practice, not optimised") and are committed *before* any run
  that uses them. Never change a parameter after seeing performance without asking the user; an
  approved change is logged there as a deviation with date and reason.
- No lookahead: `tests/test_no_lookahead.py` (features, engine, and the strategy level with
  neutral and chosen settings) must keep passing. Features at `t` use data through the close of
  `t`; macro series carry a one-session publication lag; the rank buffer, Schmitt triggers and
  monthly gate are pure functions of history.
- Never back-fill or interpolate macro data; never impute prices (missing history = exclusion).
- Every performance figure is net of costs and reported next to the equal-weight buy-and-hold
  of the same basket. Selection bias stays the first thing the README, the reports and the
  study say. Turnover figures are reported next to the average held rank.
- Verdict sentences in reports are generated from the numbers, never hard-coded. Reports lead
  with thesis, framing and verdict against buy-and-hold of the basket; SPY and naive momentum
  are appendix context; CAGR / Calmar / alpha are suppressed under 24 months
  (`risk.metrics.MIN_ANNUALISE_SESSIONS`); a "Performance by regime" section (VIX / applied
  gate / rate shock, `risk/regimes.py`) tests the macro-timing claim where it is made.

## Outputs layout

`outputs/<run.name>/{report.md, data_quality.md, figures/, target_weights.csv,
turnover_attribution.csv, held_rank.csv, feature_panel.parquet}`; `outputs/study.md` and
`outputs/study/{ablation_*.csv, *.png}`. Reports, data-quality files, PNGs and the study are
committed (`.gitignore`); a rerun on the same data is byte-identical (no git hash, no
timestamps; the hash is logged to stdout).

## Data quirks (already handled — don't re-investigate)

- FRED is read via the keyless `fredgraph.csv` endpoint; `pandas-datareader` is deliberately not used
  (its pin imports `distutils`, gone in 3.12).
- `exchange_calendars` must stay ≥ 4.13: older versions lack the 2025-01-09 NYSE closure and Korean
  ad-hoc holidays, which shows up as the same phantom gap on every ticker.
- SK Hynix (`000660.KS`): yfinance adjusted close is negative through 2002 → `regime_start_date =
  2003-01-02` in `universe.csv`. Zero-volume phantom bars on KRX holidays are dropped in
  `prices.drop_phantom_bars`. Two real gaps (2022-01-03, 2022-05-09) leave its target in cash
  that day — expected.
- Metrics are annualized on the market calendar (`BacktestResult.market_sessions`, NYSE); the
  NYSE ∪ KRX master calendar would otherwise count 3% more "years" on the control than on the
  ETF universe.
- ETF venues (NYSE Arca, Cboe BZX, NASDAQ) all map to `XNYS` in `calendar.EXCHANGE_TO_MIC`.
- The 5 M EUR liquidity screen toggles COHR and IREN on the control and moves its equal-weight
  buy-and-hold (re-equalized on every eligibility change); the study has a screen-off row.
- In block mode the gate's attributed turnover is 0 by construction with equal weights and a
  full book (blocked entries become membership when they execute); use the gate-disabled row.
- yfinance `get_earnings_dates` caps `limit` at 100, and its forward dates can be off by a day.

## Earnings dates are hand-reviewed

`data/reference/earnings_dates.csv` is seeded by `scripts/seed_earnings_dates.py` and then checked
against investor-relations calendars by the user. Never regenerate and commit it without the user
reviewing the printed spot-check list, and confirm the control run logs a nonzero
"entries blocked pre-earnings" afterwards. The ETF config has the mask disabled.

## Golden fixture

`tests/fixtures/golden_*` freeze the Layer 1 run on the wide synthetic market. Re-freeze
(`python scripts/freeze_golden.py`) only when Layer 1 behaviour is deliberately redefined, and
say so in the commit.
