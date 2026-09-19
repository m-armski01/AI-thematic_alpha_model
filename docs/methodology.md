# Methodology, robustness and project notes

Companion to the [README](../README.md), which carries the results. This file holds the rule
set, the parameter discipline, the turnover and ablation evidence, the data problems and how
they are handled, and the repository layout. Every number here is copied from the committed
reports: [`outputs/study.md`](../outputs/study.md) and `outputs/<run>/report.md`.

Module docstrings cite sections of the original build spec as "SPEC §n". That spec is not part
of this repository; the citations are kept as a record of which requirement each module meets.

## Methodology

The chosen rules, every parameter of which lives in [`configs/base.yaml`](../configs/base.yaml)
(basket, headline) and [`configs/etf.yaml`](../configs/etf.yaml) (ETF control; identical except
for the universe, the benchmark list, the report framing and the earnings-mask flag):

| Component | Rule |
|---|---|
| Universe | Basket: 12 AI-infrastructure names (`data/reference/universe.csv`), the author's holdings; control: 11 sector, 4 thematic, 2 defensive ETFs (`data/reference/universe_etf.csv`). SPY is `benchmarks[0]` in both |
| Eligibility | 252 observed sessions and a 21-day average traded value ≥ 5 M EUR (no imputation). XLRE enters 2016-10-06, XLC 2019-06-19 |
| Ranker | Cross-sectional z-score of 63-day momentum (skipping 5 days; `ranker.momentum_signal`), **equal weight** over the held set; **rank buffer**: enter at rank ≤ 5 into a vacant slot, stay while rank ≤ 8, never more than 5 names |
| Macro gate | Sub-gates on lagged VIX (engage > 25, release ≤ 20), 21-day 10y-yield change (+40 / +32 bp) and 21-day WTI change (+20% / +16%): **Schmitt triggers**, evaluated **monthly** and held between evaluations. Any engaged sub-gate = risk-off: **block increases** (no new entries, no increases for non-exempt names, exits and decreases follow the ranker, blocked weight stays in cash); `defensive` names are exempt |
| Earnings mask | Basket only: no *increase* within 3 sessions before a known earnings date; disabled on ETFs |
| Sizing | 35% per-name cap (excess to cash), 0% cash floor |
| Position band | In the engine: a held→held trade is skipped when the target is within 2 pp of the *drifted* weight; exits and entries always trade; overlay runs only |
| Schedule | Signal on the last NYSE session of each week on or before Friday; executed the next session at the open |
| Costs | 5 bp per side + 3 bp slippage on traded notional, paid from cash; buys are sized so cash never goes negative |
| Idle cash | Earns the 3-month T-bill rate (`DTB3`, calendar-day accrual, one-session publication lag) in the overlay and in every benchmark |
| Benchmarks | Equal-weight buy-and-hold of the basket (re-equalized when the eligible set changes) is the benchmark; SPY buy-and-hold and naive equal-weight top-5 momentum (no gate, no mask) are appendix context; all through the same engine and cost model, none with the band |

**Point-in-time discipline.** Every feature at date *t* uses data through the close of *t*;
the rank buffer, the Schmitt triggers, the monthly gate and the regime tags are pure functions of
history. `tests/test_no_lookahead.py` asserts (a) shifting all inputs by one day moves the
outputs with them, (b) deleting all data after *t* leaves every feature at or before *t*
unchanged, (c) a synthetic future price spike leaves no trace before it, (d) a price shock after
*t + 1* cannot alter the trade produced by a signal at *t*, and (e) deleting the future leaves
every target weight, held-rank value and trade at or before *t* unchanged, with the neutral and
the chosen settings.

**Lesson from Layer 1.** Two bugs lived in data artifacts rather than code: a wrong row in the
universe CSV, and an empty earnings CSV that made the mask fail open everywhere while every test
stayed green. Tests see code; they do not see the files the code reads. That is why the
eligibility table, the mask counts and the gate counts are printed by every run and the
earnings file is reviewed by hand.

## Parameter discipline

Every parameter was **set from standard practice, not optimised**, and written down with its
neutral (Layer 1) value, chosen value and rationale in
[`docs/preregistration_v2.md`](preregistration_v2.md) *before* the runs that use it (the
commit precedes the runs in `git log`). Every neutral default reproduces Layer 1 exactly
(`tests/test_golden.py` against a frozen fixture), the chosen values live only in the YAML
configs, and nothing was changed after seeing a result. Measurement changes (annualisation on the
market calendar, idle cash at the T-bill rate) are logged there with dates.

## Turnover: measure first, then control

Layer 1 turned the book over 18.8× a year. Every trade is attributed to a cause that sums to the
total exactly: **membership** (entries/exits), **drift**, **gate**, **reweight**.

![turnover before/after](../outputs/study/turnover_before_after.png)

| Universe | Rules | membership | drift | gate | reweight | total | **avg held rank** | costs %eq |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 12 stocks | L1 baseline | 9.18 | 0.97 | 1.75 | 6.87 | 18.77 | 3.00 | 2.61% |
| 12 stocks | chosen | 3.40 | 0.60 | 0.00 | 0.14 | 4.14 | 3.82 | 0.58% |
| 17 ETFs | L1 baseline | 15.59 | 0.36 | 1.79 | 7.26 | 25.00 | 3.00 | 14.18% |
| 17 ETFs | chosen | 9.66 | 0.09 | 0.00 | 0.00 | 9.75 | 3.55 | 5.89% |

**The held-rank trade-off.** The rank buffer (enter at rank ≤ 5, exit only below rank 8) is the
single knob that cuts turnover most, and it is not free: the average cross-sectional rank of the
held names rises from 3.0 (plain top-5, by construction) to 3.82 on the basket and 3.55 on the
ETFs. Wherever a turnover reduction is reported, that number sits next to it. In block mode the
gate's own turnover reads 0.00 because a blocked *entry* that later executes is membership
turnover; the gate-disabled row of the ablation is the honest measure of what the gate does.

## Ablation (summary; full table in `outputs/study.md`)

| | 12 stocks: Sharpe / turnover | 17 ETFs: Sharpe / turnover |
|---|---:|---:|
| L1 baseline (tiers, top-5, gate scale/weekly) | 1.08 / 18.8× | 0.34 / 25.0× |
| + equal weight | 1.11 / 16.5× | 0.45 / 23.1× |
| + rank buffer (exit rank 8) | 1.09 / 7.7× | 0.41 / 12.7× |
| + position band 2 pp | 1.09 / 6.7× | 0.41 / 12.0× |
| + gate: block increases | 1.10 / 4.5× | 0.46 / 10.2× |
| + gate: Schmitt trigger | 1.09 / 4.3× | 0.36 / 9.9× |
| + gate: monthly evaluation (= chosen) | 1.13 / 4.1× | 0.31 / 9.8× |
| chosen, gate disabled | 1.13 / 4.6× | 0.50 / 10.7× |
| chosen with softmax τ = 0.5 / 1 / 2 | 0.87 / 1.00 / 1.07 | 0.02 / 0.12 / 0.22 |
| chosen with momentum window 126 / 252 sessions | 1.17 / 1.07 | 0.61 / 0.68 |

**Sensitivity sets are reported, not harvested.** Longer momentum windows cut turnover (2.7× and
2.2× on the basket) and do better on the ETF control (Sharpe 0.61 and 0.68 against 0.31); the
chosen 63-day signal stays, because promoting the best row after the fact is exactly the practice
the preregistration rules out.

**Gate comparability across universes.** TLT and GLD change what the gate is measuring. With
defensive assets in the universe, risk-off rotation can happen through the ranker, with momentum
simply selecting bonds or gold, rather than the gate forcing cash. The two mechanisms partly
substitute for each other, so the gate's measured contribution on the ETF control is **not
directly comparable** to its contribution on the basket, where the gate is the only risk-off
mechanism. The `defensive` segment is exempt from the block rule, which is what lets that
substitution happen while the gate is risk-off.

**Where this sits in the literature.** Cross-sectional momentum on sector ETFs is tactical asset
allocation with published precedent. Faber's "A Quantitative Approach to Tactical Asset
Allocation" applies a monthly trend filter (price vs a 10-month moving average) per asset class
and moves the failing sleeve to cash; Antonacci's dual momentum combines relative strength
across assets with an absolute-momentum filter that moves to bonds, again evaluated monthly;
Moskowitz and Grinblatt (1999) documented momentum at the industry level, which is what a
sector-ETF ranker trades on; the 12-1 signal in the momentum-window sensitivity set is the
Jegadeesh–Titman / Carhart convention. The design choices here map onto that tradition: a monthly
cadence for the risk filter, top-N relative strength for selection, and a rank buffer of the
kind used in buffered index rules to cut turnover. No performance figures from those works are
quoted here because none were verified against the sources for this window.

## Known data problems and how they are handled

| Problem | Handling |
|---|---|
| The basket is the author's own selection | Stated as the framing; equal-weight buy-and-hold of the same basket is the only headline benchmark; the point-in-time ETF universe is the generalisation control |
| ETF-delisting bias | Stated; not corrected (no delisted-fund data) |
| Short histories (NBIS, IREN, XLRE, XLC) | No imputation. A name is excluded until it has 252 sessions; the composition table and figure show when each name enters |
| Illiquid periods (ITA, IGV in 2015–16; COHR, IREN) | Liquidity screen on 21-day traded value; the screen's effect is an ablation row |
| Two calendars (basket) | `exchange_calendars` sessions; master calendar = NYSE ∪ KRX; features on own sessions; metrics annualized on NYSE sessions; cash accrues on calendar days so the second calendar cannot inflate it |
| SK Hynix adjusted close negative through 2002 | `regime_start_date = 2003-01-02` truncates it |
| FRED gaps and revisions | Forward-fill only, never back-fill; one-session publication lag; current vintage, stated |
| WTI negative print (2020-04-20) | The 21-day change floors its *denominator* at $1 |
| Earnings dates (basket) | Seeded from yfinance, reviewed by hand, version-controlled; missing tickers fail open with a warning |
| Gate chattering | Measured (88 transitions, 27 reversed within a week at Layer 1), then removed at the source by the Schmitt triggers and monthly evaluation (34 transitions, 0 reversed) |

## Build status

| Layer | Status |
|---|---|
| 0 — Foundation (config, price cache, CLI, tests) | done |
| 1 — Data, features, strategy, engine, risk, report (12-stock basket) | done |
| 2.0 — Report determinism, golden fixture, SPY benchmark, preregistration | done |
| 2.1 — Turnover attribution and gate diagnostics | done |
| 2.2–2.5 — Softmax weighting, rank buffer, position band, gate redesign (block / Schmitt / monthly) | done |
| 2.6 — Point-in-time ETF universe, liquidity screen, per-run outputs | done |
| 2.7 — Study runner: control rerun + ablation, `outputs/study.md` | done |
| 2.8 — Publishable state ([`docs/history/IMPROVEMENTS.md`](history/IMPROVEMENTS.md)): idle cash at T-bills, report reframed around the owned basket with a generated verdict, performance by regime, momentum-window sensitivity, dead scaffolding removed | done |
| 2.9 — Public release: packaging, LICENSE, README as the results page, this file | done |
| Next — §13 case study (2026 YTD vs the real trade log), point-in-time *stock* universe (§15) | not started |
| Future work — walk-forward / out-of-sample split, ALFRED macro vintages, factor attribution, an ML ranker, a house-money sizing simulator | not started |

## Outputs and maintenance

Outputs per run under `outputs/<run.name>/`: `report.md`, `data_quality.md`, `figures/*.png`,
`target_weights.csv`, `turnover_attribution.csv`, `held_rank.csv`, `feature_panel.parquet`.
The study writes `outputs/study.md` and `outputs/study/` (ablation CSVs, figures). Reports are
deterministic: a rerun on the same data is byte-identical. Only `report.md`, `data_quality.md`,
the PNGs and the study files are committed; the CSV and Parquet run artefacts and the download
cache stay local (`.gitignore`).

To refresh earnings dates (basket): `python scripts/seed_earnings_dates.py`, then review the
printed spot-check list before committing `data/reference/earnings_dates.csv`. To re-freeze the
golden fixture (only when Layer 1 behaviour is deliberately redefined):
`python scripts/freeze_golden.py`.

## Layout

```
configs/base.yaml, etf.yaml      every tunable; chosen values (neutral defaults live in config.py);
                                 the report: block fixes title / subtitle / author / thesis per run
docs/methodology.md              this file
docs/preregistration_v2.md       neutral / chosen value and rationale per knob, committed before the runs
docs/history/IMPROVEMENTS.md     the work order that produced the publishable state (kept as a record)
data/reference/                  universe.csv (the basket), universe_etf.csv, earnings_dates.csv
data/cache/                      Parquet cache (gitignored)
src/thematic_alpha/
  config.py                      pydantic v2 schema; every new knob defaults to Layer 1
  data/        prices, macro (FRED CSV endpoint), calendar, fx, universe, quality, cache
  features/    price_features, macro_features, build (eligibility incl. liquidity, first dates)
  strategy/    macro_gate (Schmitt, cadence, block), ranker (softmax, rank buffer, signal knob),
               event_mask, sizing, compose (p / q / w books)
  backtest/    schedule, engine (position band, trade log, cash at rf), attribution, costs, benchmarks
  risk/        metrics (market-calendar annualization, alpha t-stat), drawdown, regimes
  reporting/   plots, tables, report (thesis / framing / verdict / regimes / appendix / limitations)
  pipeline.py                    one function per stage
  run.py                         CLI for one run
  study.py                       CLI for the ablation study
scripts/                         seed_earnings_dates.py, freeze_golden.py
tests/                           offline; synthetic markets in tests/synthetic.py, golden fixture in tests/fixtures/
outputs/                         <run>/report.md + figures (committed), study.md, study/
```
