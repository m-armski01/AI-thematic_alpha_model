# thematic-alpha report — run `base`

**Hindsight bias, stated up front.** The universe was chosen in 2026 knowing which AI names had performed well. Every absolute return figure below is inflated by that selection and is **not** achievable ex-ante. The equal-weight buy-and-hold of the *same* basket is the benchmark that isolates what the rules add on top of the selection; read the strategy column against that one, not against the S&P 500.

> Research system, not a trading system. Nothing here is investment advice. All figures are net of transaction costs.

## Configuration

| Setting | Value |
|---|---|
| Code version | `37bb025` |
| Backtest window | 2015-01-01 → latest data |
| Base currency | EUR |
| Rebalance | weekly, friday |
| Execution | t + 1 session at the open |
| Costs | model=bps, 5 bps/side + 3 bps slippage, flat 1 EUR |
| Ranker | momentum_zscore, top 5, conviction_tier |
| Macro gate | VIX>25→×0.5; 10y +40bp/21d→×0.7; WTI +20%/21d→×0.85; floor 0.3; multiplicative |
| Event mask | block new exposure 3 sessions before earnings (on) |
| Sizing | max weight 0.35, cash floor 0; house-money rule: Layer 2 (not applied) |
| Min history | 252 sessions |
| Macro publication lag | 1 session |

## Data quality

15 price series and 11 FRED series loaded; 38 single-day moves above 25% flagged for manual review. Full per-ticker table: `outputs/data_quality.md`. Known handling: SK Hynix truncated to 2003 (mis-adjusted 2002 reverse split in the source), zero-volume bars on Korean holidays dropped, master calendar = NYSE ∪ KRX sessions with forward-fill only across a name's own holidays.

## Strategy activity

611 signal dates. Macro-gate exposure averaged 0.92 (minimum 0.30; below 1.0 on 118 signal dates). Event mask: **66 entries blocked pre-earnings** (323 ticker-dates masked; 0 tickers without earnings dates failed open).

## Headline results (net of costs)

![equity curves](figures/equity_curves.png)

| Metric | Strategy | S&P 500 (^GSPC) B&H | Equal-weight B&H (universe) | Naive momentum (top-N) |
|---|---:|---:|---:|---:|
| Total return | 4353.6% | 282.0% | 7474.4% | 6780.2% |
| CAGR | 37.1% | 11.8% | 43.3% | 42.2% |
| Annualized volatility | 32.6% | 18.5% | 31.2% | 34.0% |
| Sharpe (excess over DTB3) | 1.07 | 0.58 | 1.24 | 1.14 |
| Sortino (MAR 0) | 1.56 | 0.82 | 1.82 | 1.67 |
| Max drawdown | -50.8% | -33.7% | -46.7% | -55.2% |
| Max DD peak | 2021-11-25 | 2020-02-19 | 2021-12-27 | 2022-01-03 |
| Max DD trough | 2022-12-28 | 2020-03-23 | 2022-12-28 | 2022-12-28 |
| Max DD recovery | 2023-07-03 | 2021-01-20 | 2023-07-05 | 2024-02-09 |
| Max DD duration (days) | 585 | 336 | 555 | 767 |
| Calmar | 0.73 | 0.35 | 0.93 | 0.76 |
| Alpha vs S&P 500 (ann.) | 23.4% | -0.1% | 24.7% | 25.0% |
| Beta vs S&P 500 | 1.05 | 1.00 | 1.29 | 1.27 |
| Historical VaR 95% (daily) | 3.1% | 1.7% | 3.2% | 3.3% |
| Historical VaR 99% (daily) | 5.8% | 3.4% | 5.3% | 5.8% |
| Parametric VaR 95% (daily) | 3.2% | 1.9% | 3.1% | 3.4% |
| Parametric VaR 99% (daily) | 4.6% | 2.7% | 4.4% | 4.8% |
| CVaR / ES 95% (daily) | 4.8% | 2.8% | 4.6% | 5.0% |
| Excess kurtosis (daily) | 3.72 | 12.39 | 3.70 | 3.42 |
| Hit rate (weekly periods) | 59.9% | 59.8% | 61.7% | 60.4% |
| Average win (weekly period) | 3.6% | 1.7% | 3.5% | 3.8% |
| Average loss (weekly period) | -3.6% | -1.8% | -3.5% | -3.7% |
| Annualized turnover | 18.32 | 0.08 | 0.62 | 15.39 |
| Total costs paid | 11,464.76 | 7.99 | 1,229.48 | 13,034.81 |
| Costs as % of final equity | 2.57% | 0.02% | 0.16% | 1.89% |

Against equal-weight buy-and-hold of the same basket the strategy's CAGR is lower (37.1% vs 43.3%), its Sharpe is lower (1.07 vs 1.24), and its maximum drawdown is deeper (-50.8% vs -46.7%). **This is an underperformance result**: the rules did not add value over simply holding the (hindsight-selected) basket, net of costs.

VaR note: parametric (normal) 99% VaR is 4.6% against a historical 5.8%; daily excess kurtosis is 3.72. The normal assumption understates the tail.

## FX decomposition (strategy)

|  | In EUR | In local currencies |
|---|---:|---:|
| Total return | 4353.6% | 4022.9% |
| CAGR | 37.1% | 36.2% |

FX contribution: 0.9% per year of CAGR; in total the EUR result differs from the local-currency result by 330.7% of initial capital. Positions are unhedged USD and KRW exposure held by a EUR investor.

## Largest drawdowns

**Strategy**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -50.8% | 2021-11-25 | 2022-12-28 | 2023-07-03 | 585 |
| -46.9% | 2024-12-04 | 2025-04-21 | 2025-08-29 | 268 |
| -37.2% | 2024-06-18 | 2024-08-07 | 2024-12-04 | 169 |
| -33.2% | 2026-06-22 | 2026-07-29 | not recovered | 81 |
| -32.9% | 2018-07-25 | 2018-12-24 | 2021-01-04 | 894 |

**Equal-weight B&H (universe)**

| Depth | Peak | Trough | Recovery | Duration (days) |
|---|---:|---:|---:|---:|
| -46.7% | 2021-12-27 | 2022-12-28 | 2023-07-05 | 555 |
| -41.5% | 2025-01-23 | 2025-04-21 | 2025-07-09 | 167 |
| -33.4% | 2020-02-19 | 2020-03-16 | 2020-07-02 | 134 |
| -32.2% | 2018-08-31 | 2018-12-24 | 2019-05-03 | 245 |
| -29.8% | 2024-06-18 | 2024-08-07 | 2024-11-07 | 142 |

## Figures

![Strategy underwater plot](figures/underwater.png)

![Rolling 12-month Sharpe (strategy)](figures/rolling_sharpe.png)

![Rolling beta vs S&P 500 (strategy)](figures/rolling_beta.png)

![Allocation over time](figures/weights.png)

![Macro-gate exposure and VIX](figures/gate_vs_vix.png)
