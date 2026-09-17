# thematic-alpha report — run `etf_2026ytd`

**Universe definition (point-in-time).** The universe is a fixed list of 17 exchange-traded funds chosen by category (2 defensive, 11 sector, 4 thematic), not by past performance, from `data/reference/universe_etf.csv`. A name enters the cross-section only once it has 252 observed sessions and a 21-day average traded value of at least 5,000,000 EUR, so the investable set on every signal date is defined from data available on that date (composition table and figure below). Residual bias: the list holds only funds that still trade at the snapshot date; funds in these categories that were liquidated or merged away are absent, which flatters the equal-weight buy-and-hold of the basket (ETF-delisting bias). It is much smaller than hindsight stock selection, but it is not zero.

> Research system, not a trading system. Nothing here is investment advice. All figures are net of transaction costs.

## Configuration

| Setting | Value |
|---|---|
| Backtest window | 2026-01-01 → 2026-09-11 |
| Universe | `data/reference/universe_etf.csv`, 17 names, selection: point_in_time; market: SPY |
| Base currency | EUR |
| Rebalance | weekly, friday |
| Execution | t + 1 session at the open |
| Costs | model=bps, 5 bps/side + 3 bps slippage, flat 1 EUR |
| Ranker | momentum_zscore, top 5 (exit rank 8), equal |
| Macro gate | block increases while any sub-gate is engaged (VIX>25 (release 20); 10y +40bp (release 32bp)/21d; WTI +20% (release 16%)/21d); exempt segments: defensive; scale factors and floor unused; evaluated monthly |
| Event mask | disabled |
| Sizing | max weight 0.35, cash floor 0 |
| Liquidity screen | 21-day average traded value ≥ 5,000,000 EUR |
| Turnover control | position no-trade band 2 pp (on; strategy only) |
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

## Strategy activity

37 signal dates. Macro gate in **block-increases** mode: risk-off on 8 signal dates, 9 increases or entries blocked (that weight stayed in cash; exempt names: TLT, GLD). The scale factors and `min_exposure` are unused in this mode. The gate was evaluated on 10 of the 37 signal dates (monthly) and held constant in between; ranking stayed weekly. Event mask: **disabled** (ETFs report no earnings; nothing to mask).

Average cross-sectional rank of the held names: **3.61** (exit rank 8, top 5; plain top-5 gives 3.0 by construction). A higher value is the signal-quality cost of the rank buffer: it holds names the ranker would otherwise have replaced.

## Headline results (net of costs)

![equity curves](figures/equity_curves.png)

| Metric | Strategy | S&P 500 (SPY) B&H | Equal-weight B&H (universe) | Naive momentum (top-N) |
|---|---:|---:|---:|---:|
| Total return | 16.5% | 12.8% | 11.0% | 20.6% |
| CAGR | 24.8% | 19.0% | 16.4% | 31.2% |
| Annualized volatility | 16.7% | 12.7% | 10.5% | 16.9% |
| Sharpe (excess over DTB3) | 1.19 | 1.15 | 1.15 | 1.48 |
| Sortino (MAR 0) | 1.89 | 1.70 | 1.73 | 2.23 |
| Max drawdown | -7.3% | -7.5% | -5.8% | -8.7% |
| Max DD peak | 2026-03-02 | 2026-01-09 | 2026-03-02 | 2026-03-02 |
| Max DD trough | 2026-03-23 | 2026-03-27 | 2026-03-27 | 2026-03-23 |
| Max DD recovery | 2026-05-29 | 2026-04-16 | 2026-05-06 | 2026-05-14 |
| Max DD duration (days) | 88 | 97 | 65 | 73 |
| Calmar | 3.38 | 2.54 | 2.82 | 3.57 |
| Alpha vs S&P 500 (ann.) | 5.4% | -1.2% | 0.6% | 11.3% |
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

Against equal-weight buy-and-hold of the same basket the strategy's CAGR is higher (24.8% vs 16.4%), its Sharpe is higher (1.19 vs 1.15), and its maximum drawdown is deeper (-7.3% vs -5.8%).

VaR note: parametric (normal) 99% VaR is 2.3% against a historical 2.0%; daily excess kurtosis is 1.13. The normal assumption does not understate the 99% tail here.

## Turnover attribution

Annualized turnover split by cause (see `backtest/attribution.py`): **membership** (entries and exits), **drift** (re-trading a held name back to an unchanged target, including the residual of earlier skipped or cash-scaled trades), **gate** (the macro gate changing the book) and **reweight** (ranker, mask and cap effects on a held name). Causes sum to the annualized turnover in the table above.

| Run | membership | drift | gate | reweight | total |
|---|---:|---:|---:|---:|---:|
| Strategy | 10.62 | 0.17 | 0.00 | 0.00 | 10.79 |
| S&P 500 (SPY) B&H | 1.45 | 0.00 | 0.00 | 0.00 | 1.45 |
| Equal-weight B&H (universe) | 1.45 | 0.00 | 0.00 | 0.00 | 1.45 |
| Naive momentum (top-N) | 24.69 | 0.93 | 0.00 | 0.00 | 25.63 |

Macro gate: 4 state transitions over 37 signal dates (5.8 per year); 0 of them reverse within 1 signal date and 0 within 2. The gate accounts for 0.0% of the strategy's turnover. In block mode a blocked *entry* that executes after the release is membership turnover, not gate turnover, so this share only counts blocked increases of held names; with equal weights and a full book those are rare, and the gate's effect shows up as deferred membership and higher cash instead.

![turnover by cause](figures/turnover_by_cause.png)

## FX decomposition (strategy)

|  | In EUR | In local currencies |
|---|---:|---:|
| Total return | 16.5% | 14.9% |
| CAGR | 24.8% | 22.3% |

FX contribution: 2.5% per year of CAGR; in total the EUR result differs from the local-currency result by 1.6% of initial capital. Positions are unhedged USD exposure held by a EUR investor.

## Largest drawdowns

**Strategy**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -7.3% | 2026-03-02 | 2026-03-23 | 2026-05-29 | 88 |
| -6.6% | 2026-06-02 | 2026-07-29 | 2026-08-10 | 69 |
| -3.3% | 2026-09-02 | 2026-09-10 | not recovered | 9 |
| -2.6% | 2026-01-21 | 2026-02-05 | 2026-02-06 | 16 |
| -1.7% | 2026-01-16 | 2026-01-20 | 2026-01-21 | 5 |

**Equal-weight B&H (universe)**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -5.8% | 2026-03-02 | 2026-03-27 | 2026-05-06 | 65 |
| -3.8% | 2026-08-13 | 2026-09-10 | not recovered | 29 |
| -3.0% | 2026-01-15 | 2026-02-05 | 2026-02-18 | 34 |
| -2.5% | 2026-07-06 | 2026-07-31 | 2026-08-07 | 32 |
| -2.5% | 2026-06-04 | 2026-06-10 | 2026-06-15 | 11 |

## Figures

![Strategy underwater plot](figures/underwater.png)

![Rolling 12-month Sharpe (strategy)](figures/rolling_sharpe.png)

![Rolling beta vs S&P 500 (strategy)](figures/rolling_beta.png)

![Allocation over time](figures/weights.png)

![Applied macro-gate state and VIX](figures/gate_vs_vix.png)
