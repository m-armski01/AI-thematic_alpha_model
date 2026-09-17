# Does the overlay generalise? Point-in-time ETF control — run `etf_2026ytd`

*Out-of-basket robustness check: the same rules on 17 sector, factor and defensive ETFs, 2026 year-to-date (window under 24 months: annualised metrics suppressed)*

**Thesis.** The overlay's value, if any, should not depend on the author's particular names. Running the identical rules on a category-defined, point-in-time ETF universe tests whether the macro gate and the momentum ranker add anything to buy-and-hold when the basket carries no hindsight; if the overlay helps only on the basket, the basket and not the rules is the source.

**Control universe (point-in-time).** This run is the generalisation check for the overlay, not the headline: a fixed list of 17 exchange-traded funds chosen by category (2 defensive, 11 sector, 4 thematic), not by past performance, from `data/reference/universe_etf.csv`. A name enters the cross-section only once it has 252 observed sessions and a 21-day average traded value of at least 5,000,000 EUR, so the investable set on every signal date is defined from data available on that date (composition table and figure below). If the overlay adds value on the author's basket but not here, the basket rather than the rules is the source. Residual bias: the list holds only funds that still trade at the snapshot date; funds in these categories that were liquidated or merged away are absent, which flatters buy-and-hold of the control basket (ETF-delisting bias). It is much smaller than hindsight stock selection, but it is not zero.

> Research system, not a trading system. Nothing here is investment advice. All figures are net of transaction costs.

## Verdict

Over 2026-01-01 → 2026-09-11 (8 months) the overlay's total return is higher than equal-weight buy-and-hold of the same basket (16.5% vs 11.0%), its Sharpe is higher (1.19 vs 1.15), and its maximum drawdown is deeper (-7.3% vs -5.8%). Realised beta to the S&P 500 is 0.91 for the overlay and 0.72 for buy-and-hold, so the extra return comes with more market exposure, not less. **The overlay adds return and risk-adjusted return, at the cost of a deeper drawdown**, net of costs. Annualised figures are omitted: an 8-month window is under the 24 months this report requires, and it is too short to conclude either way.

## Headline results (net of costs): overlay vs buy-and-hold of the basket

![equity curves](figures/equity_curves.png)

| Metric | Overlay | Equal-weight buy-and-hold (basket) |
|---|---:|---:|
| Total return | 16.5% | 11.0% |
| CAGR | n/a (8-month window) | n/a (8-month window) |
| Annualized volatility | 16.7% | 10.5% |
| Sharpe (excess over DTB3) | 1.19 | 1.15 |
| Sortino (MAR 0) | 1.89 | 1.73 |
| Max drawdown | -7.3% | -5.8% |
| Max DD peak | 2026-03-02 | 2026-03-02 |
| Max DD trough | 2026-03-23 | 2026-03-27 |
| Max DD recovery | 2026-05-29 | 2026-05-06 |
| Max DD duration (days) | 88 | 65 |
| Calmar | n/a (8-month window) | n/a (8-month window) |
| Historical VaR 95% (daily) | 1.6% | 1.0% |
| Historical VaR 99% (daily) | 2.0% | 1.5% |
| Parametric VaR 95% (daily) | 1.6% | 1.0% |
| Parametric VaR 99% (daily) | 2.3% | 1.5% |
| CVaR / ES 95% (daily) | 2.0% | 1.4% |
| Excess kurtosis (daily) | 1.13 | 1.68 |
| Hit rate (weekly periods) | 62.9% | 57.1% |
| Average win (weekly period) | 1.6% | 1.2% |
| Average loss (weekly period) | -1.4% | -0.8% |
| Annualized turnover | 10.79 | 1.45 |
| Total costs paid | 64.91 | 8.00 |
| Costs as % of final equity | 0.56% | 0.07% |

Annualised rows (CAGR, Calmar, alpha) are not reported: the window covers 8 months and the report annualises only over 24 or more.

VaR note: parametric (normal) 99% VaR of the overlay is 2.3% against a historical 2.0%; daily excess kurtosis is 1.13. The normal assumption does not understate the 99% tail here.

## Performance by regime

The overlay is a macro-timing rule, so it is tested where it claims to help. Every session is tagged by the state the gate could see that day and the overlay is compared with equal-weight buy-and-hold inside each bucket: VIX calm below 20, elevated between 20 and 25, stress above 25; gate risk-off / risk-on as applied to the book; rate shock when the 21-day change in the 10-year yield exceeds 40 bp. Total return compounds the bucket's sessions and the worst drawdown is measured on that concatenated path; an annualised return is shown only for buckets with at least 24 months of sessions.

**By VIX regime (lagged level the gate reads)**

| Regime | Run | Share of sessions | Total return | Annualised | Volatility | Hit rate (sessions) | Worst drawdown |
|---|---|---:|---:|---:|---:|---:|---:|
| calm | Overlay | 78.7% | 7.4% | n/a | 16.2% | 51.1% | -10.3% |
| calm | Equal-weight buy-and-hold (basket) | 78.7% | 5.4% | n/a | 9.1% | 55.5% | -5.0% |
| elevated | Overlay | 13.2% | 7.3% | n/a | 21.6% | 56.5% | -6.5% |
| elevated | Equal-weight buy-and-hold (basket) | 13.2% | 3.0% | n/a | 16.1% | 60.9% | -5.6% |
| stress | Overlay | 8.0% | 1.2% | n/a | 12.0% | 64.3% | -1.6% |
| stress | Equal-weight buy-and-hold (basket) | 8.0% | 2.3% | n/a | 12.2% | 64.3% | -1.7% |

**By applied gate state**

| Regime | Run | Share of sessions | Total return | Annualised | Volatility | Hit rate (sessions) | Worst drawdown |
|---|---|---:|---:|---:|---:|---:|---:|
| risk-on | Overlay | 77.6% | 5.7% | n/a | 17.4% | 51.1% | -8.5% |
| risk-on | Equal-weight buy-and-hold (basket) | 77.6% | 3.3% | n/a | 10.8% | 55.6% | -5.6% |
| risk-off | Overlay | 22.4% | 10.2% | n/a | 13.9% | 59.0% | -2.5% |
| risk-off | Equal-weight buy-and-hold (basket) | 22.4% | 7.5% | n/a | 8.9% | 61.5% | -2.0% |

**By 10-year yield change (rate shock = above the gate's engage threshold)**

| Regime | Run | Share of sessions | Total return | Annualised | Volatility | Hit rate (sessions) | Worst drawdown |
|---|---|---:|---:|---:|---:|---:|---:|
| no shock | Overlay | 98.9% | 15.1% | n/a | 16.7% | 52.3% | -7.3% |
| no shock | Equal-weight buy-and-hold (basket) | 98.9% | 9.5% | n/a | 10.5% | 56.4% | -5.8% |
| rate shock | Overlay | 1.1% | 1.2% | n/a | 9.5% | 100.0% | 0.0% |
| rate shock | Equal-weight buy-and-hold (basket) | 1.1% | 1.4% | n/a | 6.7% | 100.0% | 0.0% |

In the VIX stress regime (8.0% of sessions) the overlay returns 1.2% against 2.3% for buy-and-hold, with a worst drawdown of -1.6% vs -1.7%; while the gate is risk-off (22.4% of sessions) the overlay returns 10.2% against 7.5% for buy-and-hold, with a worst drawdown of -2.5% vs -2.0%; during rate shocks (1.1% of sessions) the overlay returns 1.2% against 1.4% for buy-and-hold, with a worst drawdown of 0.0% vs 0.0%. **The regime evidence is mixed**: the overlay beats holding the basket in 1 of 3 stress buckets.

## Configuration

| Setting | Value |
|---|---|
| Backtest window | 2026-01-01 → 2026-09-11 |
| Universe | `data/reference/universe_etf.csv`, 17 names, selection: point_in_time; market: SPY |
| Base currency | EUR |
| Rebalance | weekly, friday |
| Execution | t + 1 session at the open |
| Costs | model=bps, 5 bps/side + 3 bps slippage, flat 1 EUR |
| Idle cash | earns DTB3 (calendar-day accrual), all runs |
| Ranker | momentum_zscore on mom_63, top 5 (exit rank 8), equal |
| Macro gate | block increases while any sub-gate is engaged (VIX>25 (release 20); 10y +40bp (release 32bp)/21d; WTI +20% (release 16%)/21d); exempt segments: defensive; scale factors and floor unused; evaluated monthly |
| Event mask | disabled |
| Sizing | max weight 0.35, cash floor 0 |
| Liquidity screen | 21-day average traded value ≥ 5,000,000 EUR |
| Turnover control | position no-trade band 2 pp (on; overlay only) |
| Min history | 252 sessions |
| Macro publication lag | 1 session |

## Data quality

18 price series and 11 FRED series loaded; 0 single-day moves above 25% flagged for manual review. Full per-ticker table: `data_quality.md` next to this report. All names trade on US venues, so the master calendar is the NYSE session calendar; no cross-exchange alignment was needed.

## Universe composition

When each name enters the cross-section (backtest starts 2026-01-02; a date before that means the name was eligible from the first signal date). Liquidity-eligible is the first date the 21-day average traded value clears the screen.

| Ticker | First price | History-eligible | Liquidity-eligible | First eligible | Enters |
|---|---|---|---|---|---|
| XLK | 1998-12-22 | 1999-12-21 | 1999-02-02 | 1999-12-21 | from start |
| XLF | 1998-12-22 | 1999-12-21 | 1999-09-21 | 1999-12-21 | from start |
| XLE | 1998-12-22 | 1999-12-21 | 1999-03-12 | 1999-12-21 | from start |
| XLV | 1998-12-22 | 1999-12-21 | 2000-01-13 | 2000-01-13 | from start |
| XLY | 1998-12-22 | 1999-12-21 | 1999-12-27 | 1999-12-27 | from start |
| XLP | 1998-12-22 | 1999-12-21 | 1999-12-22 | 1999-12-22 | from start |
| XLI | 1998-12-22 | 1999-12-21 | 1999-12-27 | 1999-12-27 | from start |
| XLU | 1998-12-22 | 1999-12-21 | 2000-06-27 | 2000-06-27 | from start |
| XLB | 1998-12-22 | 1999-12-21 | 1999-04-30 | 2000-01-03 | from start |
| XLRE | 2015-10-08 | 2016-10-06 | 2016-09-12 | 2016-10-06 | from start |
| XLC | 2018-06-19 | 2019-06-19 | 2018-07-18 | 2019-06-19 | from start |
| SMH | 2000-06-05 | 2001-06-04 | 2000-07-03 | 2001-06-04 | from start |
| IGV | 2001-07-17 | 2002-07-22 | 2001-12-04 | 2002-07-22 | from start |
| IBB | 2001-02-12 | 2002-02-15 | 2001-06-11 | 2002-02-15 | from start |
| ITA | 2006-05-05 | 2007-05-07 | 2007-08-30 | 2007-08-30 | from start |
| TLT | 2002-07-30 | 2003-07-29 | 2002-08-27 | 2003-07-29 | from start |
| GLD | 2004-11-18 | 2005-11-16 | 2004-12-17 | 2005-11-16 | from start |

![universe composition](figures/universe_composition.png)

## Overlay activity

37 signal dates. Macro gate in **block-increases** mode: risk-off on 8 signal dates, 9 increases or entries blocked (that weight stays in cash; exempt names: TLT, GLD). The scale factors and `min_exposure` are unused in this mode. The gate is evaluated on 10 of the 37 signal dates (monthly) and held constant in between; ranking stays weekly. Event mask: **disabled** (ETFs report no earnings; nothing to mask).

Average cross-sectional rank of the held names: **3.61** (exit rank 8, top 5; plain top-5 gives 3.0 by construction). A higher value is the signal-quality cost of the rank buffer: it holds names the ranker would otherwise have replaced.

## Turnover attribution

Annualized turnover split by cause (see `backtest/attribution.py`): **membership** (entries and exits), **drift** (re-trading a held name back to an unchanged target, including the residual of earlier skipped or cash-scaled trades), **gate** (the macro gate changing the book) and **reweight** (ranker, mask and cap effects on a held name). Causes sum to the annualized turnover in the headline table.

| Run | membership | drift | gate | reweight | total |
|---|---:|---:|---:|---:|---:|
| Overlay | 10.62 | 0.17 | 0.00 | 0.00 | 10.79 |
| S&P 500 (SPY) buy-and-hold | 1.45 | 0.00 | 0.00 | 0.00 | 1.45 |
| Equal-weight buy-and-hold (basket) | 1.45 | 0.00 | 0.00 | 0.00 | 1.45 |
| Naive momentum (top-N) | 24.69 | 0.93 | 0.00 | 0.00 | 25.63 |

Macro gate: 4 state transitions over 37 signal dates (5.8 per year); 0 of them reverse within 1 signal date and 0 within 2. The gate accounts for 0.0% of the overlay's turnover. In block mode a blocked *entry* that executes after the release is membership turnover, not gate turnover, so this share only counts blocked increases of held names; with equal weights and a full book those are rare, and the gate's effect shows up as deferred membership and higher cash instead.

![turnover by cause](figures/turnover_by_cause.png)

## FX decomposition (overlay)

|  | In EUR | In local currencies |
|---|---:|---:|
| Total return | 16.5% | 14.9% |

FX contribution: in total the EUR result differs from the local-currency result by 1.6% of initial capital. Positions are unhedged USD exposure held by a EUR investor.

## Largest drawdowns

**Overlay**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -7.3% | 2026-03-02 | 2026-03-23 | 2026-05-29 | 88 |
| -6.6% | 2026-06-02 | 2026-07-29 | 2026-08-10 | 69 |
| -3.3% | 2026-09-02 | 2026-09-10 | not recovered | 9 |
| -2.6% | 2026-01-21 | 2026-02-05 | 2026-02-06 | 16 |
| -1.7% | 2026-01-16 | 2026-01-20 | 2026-01-21 | 5 |

**Equal-weight buy-and-hold (basket)**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -5.8% | 2026-03-02 | 2026-03-27 | 2026-05-06 | 65 |
| -3.8% | 2026-08-13 | 2026-09-10 | not recovered | 29 |
| -3.0% | 2026-01-15 | 2026-02-05 | 2026-02-18 | 34 |
| -2.5% | 2026-07-06 | 2026-07-31 | 2026-08-07 | 32 |
| -2.5% | 2026-06-04 | 2026-06-10 | 2026-06-15 | 11 |

## Appendix: market context

The S&P 500 (SPY) and a naive top-N momentum rule (no gate, no mask, no rank buffer, same costs) are shown for context only; neither is the benchmark this study is about.

| Metric | Overlay | S&P 500 (SPY) buy-and-hold | Equal-weight buy-and-hold (basket) | Naive momentum (top-N) |
|---|---:|---:|---:|---:|
| Total return | 16.5% | 12.8% | 11.0% | 20.6% |
| CAGR | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) |
| Annualized volatility | 16.7% | 12.7% | 10.5% | 16.9% |
| Sharpe (excess over DTB3) | 1.19 | 1.15 | 1.15 | 1.48 |
| Sortino (MAR 0) | 1.89 | 1.70 | 1.73 | 2.23 |
| Max drawdown | -7.3% | -7.5% | -5.8% | -8.7% |
| Max DD peak | 2026-03-02 | 2026-01-09 | 2026-03-02 | 2026-03-02 |
| Max DD trough | 2026-03-23 | 2026-03-27 | 2026-03-27 | 2026-03-23 |
| Max DD recovery | 2026-05-29 | 2026-04-16 | 2026-05-06 | 2026-05-14 |
| Max DD duration (days) | 88 | 97 | 65 | 73 |
| Calmar | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) |
| Alpha vs S&P 500 (ann.) | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) | n/a (8-month window) |
| Beta vs S&P 500 | 0.91 | 0.99 | 0.72 | 0.86 |
| Historical VaR 95% (daily) | 1.6% | 1.3% | 1.0% | 1.6% |
| Historical VaR 99% (daily) | 2.0% | 1.7% | 1.5% | 2.3% |
| Parametric VaR 95% (daily) | 1.6% | 1.2% | 1.0% | 1.6% |
| Parametric VaR 99% (daily) | 2.3% | 1.8% | 1.5% | 2.4% |
| CVaR / ES 95% (daily) | 2.0% | 1.7% | 1.4% | 2.2% |
| Excess kurtosis (daily) | 1.13 | 1.40 | 1.68 | 0.52 |
| Hit rate (weekly periods) | 62.9% | 57.1% | 57.1% | 65.7% |
| Average win (weekly period) | 1.6% | 1.5% | 1.2% | 1.8% |
| Average loss (weekly period) | -1.4% | -1.1% | -0.8% | -1.7% |
| Annualized turnover | 10.79 | 1.45 | 1.45 | 25.63 |
| Total costs paid | 64.91 | 8.00 | 8.00 | 156.18 |
| Costs as % of final equity | 0.56% | 0.07% | 0.07% | 1.29% |

Against the S&P 500 the overlay's beta is 0.91; alpha is not annualised over an 8-month window (daily-alpha t = 0.37). The alpha estimate is not distinguishable from zero at conventional levels.

## Limitations and next steps

- **ETF-delisting bias.** The control lists only funds that still trade at the snapshot date; liquidated or merged funds in the same categories are absent, which flatters buy-and-hold of the control basket.
- **Flat slippage.** Costs are 5 bps per side plus 3 bps slippage on every name regardless of size, which is optimistic for the smaller names and for re-entries after a gate release.
- **Short window.** 8 months of data; annualised statistics are suppressed and no verdict on the overlay can be drawn from this run alone.
- **No walk-forward.** Every parameter was set from standard practice and preregistered before the run, but there is no out-of-sample split; the ablation and sensitivity sets in `outputs/study.md` are the only robustness evidence.
- **Latest-revision macro data.** FRED series carry a one-session publication lag but are the current revision, not the vintage available on the day.
- **Next steps.** The 2026 case study against the real trade log, a point-in-time stock universe, and an out-of-sample split once the live window is long enough to support one.

## Figures

![Overlay underwater plot](figures/underwater.png)

![Rolling 12-month Sharpe (overlay)](figures/rolling_sharpe.png)

![Rolling beta vs S&P 500 (overlay)](figures/rolling_beta.png)

![Allocation over time](figures/weights.png)

![Applied macro-gate state and VIX](figures/gate_vs_vix.png)
