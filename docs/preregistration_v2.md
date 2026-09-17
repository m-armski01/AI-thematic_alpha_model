# Preregistration — brief v2 (point-in-time ETF universe + turnover control)

Committed **before** any run that uses these values. Every parameter below is *set from
standard practice, not optimised*: none of them was chosen after looking at a performance
result on this data. If a value changes later, the change is logged in the
[Deviations](#deviations) section with the date and the reason, and the run that motivated it is
named.

Data snapshot: prices and FRED series through **2026-09-11** (`run.end_date` is pinned to that
date in both configs and served from the Parquet cache).

## Neutral defaults

Every new parameter has a pydantic default that reproduces Layer 1 exactly (verified by
`tests/test_golden.py` against the frozen fixture). Chosen values live only in the YAML configs
(`configs/base.yaml` for the 12-stock control, `configs/etf.yaml` for the ETF universe); the two
configs share every chosen value, the window and the costs.

## Parameters

| Parameter | Neutral (= Layer 1) | Chosen | Rationale |
|---|---|---|---|
| `ranker.weighting` | `conviction_tier` (30/25/20/15/10%) | `equal` | Rank-tier weights re-trade every rank swap inside the held set (a swap between ranks 1 and 2 moves 5 pp on each name); equal weight makes a swap free. 1/N is the standard robustness benchmark for small baskets (DeMiguel, Garlappi & Uppal 2009 make the case that estimation error swamps the gain from optimised weights). Set from standard practice, not optimised. |
| `ranker.softmax_temperature` (τ) | 1.0 (unused unless `weighting: softmax`) | 1.0; sensitivity τ ∈ {0.5, 1, 2} | Softmax over the held names' momentum z-scores spans the concentration spectrum from equal weight (τ → ∞) to winner-take-all (τ → 0); the three values are declared as a sensitivity set, reported next to each other, and none is promoted to the chosen config. Set from standard practice, not optimised. |
| `ranker.exit_rank` | `None` (→ `top_n` = 5) | 8 | A rank buffer (enter at ≤ 5, exit only below 8) is the standard turnover control in rank-based index construction and momentum-index methodology (buffer rules). 8 = top_n + 3 keeps a name through the ordinary rank noise of a 12-to-17-name cross-section without letting it fall into the bottom third. The signal-quality cost is reported as the average rank of held names next to every turnover figure. Set from standard practice, not optimised. |
| `turnover.position_band` | 0.0 | 0.02 | A held name is not re-traded while its drifted weight is within 2 pp of target. At a 20% average position this is a 10%-relative no-trade band, the conventional rebalancing tolerance in institutional rebalancing policy. Full exits and new entries always trade. Set from standard practice, not optimised. |
| `macro_gate.action` | `scale` | `block_increases` | Layer 1 scaled every position by the gate multiplier, so each gate flip forced a round trip on the whole book. Blocking increases (no new risk while risk-off; decreases and exits still follow the ranker; blocked weight stays in cash) is how discretionary risk-off is actually practised and removes the gate's forced trades at the source. In block mode the scale factors and `min_exposure` are unused. Set from standard practice, not optimised. |
| `macro_gate.block_exempt_segments` | `[]` | `["defensive"]` | TLT and GLD are the assets a risk-off rotation moves *into*; exempting the `defensive` segment from the block lets the ranker rotate into them while risk-off. No-op on the stock control (no defensive names). Set from standard practice, not optimised. |
| `macro_gate.vix_release_threshold` | `None` (= engage, 25) | 20 | Schmitt trigger: engage above 25, release only at or below 20. "VIX above 25 = stress, below 20 = calm" is the common practitioner convention, and a 20% band is wide enough that the day-to-day VIX noise of 1–2 points cannot flip the state. Set from standard practice, not optimised. |
| `macro_gate.yield_release_threshold` | `None` (= engage, +0.40) | +0.32 | Release = 0.8 × engage, copying VIX's ratio so all three sub-gates carry the same relative hysteresis. Set from standard practice, not optimised. |
| `macro_gate.oil_release_threshold` | `None` (= engage, +0.20) | +0.16 | Release = 0.8 × engage, as above. Set from standard practice, not optimised. |
| `macro_gate.evaluation` | `weekly` | `monthly` | The gate state is sampled on the last weekly signal date of each month (plus the first signal date) and held between evaluations; ranking stays weekly. Macro regimes move slower than cross-sectional momentum, and the published trend / risk filters (Faber's GTAA, Antonacci's dual momentum) are evaluated monthly; weekly evaluation claims a precision the macro signal does not have. Set from standard practice, not optimised. |
| `data.min_dollar_volume_21d` | 0.0 (off) | 5,000,000 EUR | A name is eligible only once its 21-day average daily traded value in base currency reaches 5 M EUR, so a retail-size position (a few thousand EUR at 35% max weight on a 10 k EUR book) is below 0.1% of daily volume. Applied only when > 0 so 0 is byte-identical to Layer 1. Set from standard practice, not optimised. |
| `universe.selection` | `hindsight` | `point_in_time` (ETF config only) | Report framing, not a strategy parameter: `hindsight` prints the Layer 1 hindsight paragraph; `point_in_time` states how the universe was defined and the residual ETF-delisting bias. |
| `event_mask.enabled` | `true` | `false` (ETF config only) | ETFs report no earnings; the mask has nothing to mask. The control keeps it on. |
| `backtest.cash_earns_rf` | `false` | `true` (all configs) | Measurement, not a rule: idle cash earns the 3-month T-bill rate (`DTB3`, calendar-day basis) for the strategy and every benchmark alike. The overlay deliberately moves to cash when the gate blocks; charging that cash 0% would understate it against the real alternative (T-bills) and overstate it against a fully invested buy-and-hold in a zero-rate world. Off in the neutral default so the golden fixture is unchanged. |

## Dropped from the brief, and why

- **Exposure band on the gate (brief §9).** In scale mode the gate exposure can only take the
  values {1, .85, .70, .595, .50, .425, .35, .30} (products of the three scale factors, floored
  at 0.30), so the smallest possible move is 15 pp and a 5 pp band would never fire. Chattering
  is attacked at its source instead: the Schmitt trigger (b) and the monthly evaluation (c).
- **Minimum position weight.** The bps cost model has no per-trade fixed fee, so a tiny position
  costs nothing extra and a floor would be a rule without a cost rationale. Not implemented; to
  be revisited if the flat-fee model is ever used.
- **Linear z-proportional and raw-momentum weighting.** Not implemented. Softmax with τ already
  spans the concentration spectrum with one parameter, is shift-invariant and is defined for
  any real z (no clipping, no all-negative fallback needed).

## Study design (declared before the run)

`python -m thematic_alpha.study --configs configs/etf.yaml configs/base.yaml`, one pass, both
universes, same window (2015-01-01 → 2026-09-11) and costs (5 bps/side + 3 bps slippage):

- **L1 baseline**: conviction tiers, `exit_rank = top_n`, band 0, gate scale / weekly / no
  Schmitt.
- **Cumulative**: + equal weight → + hysteresis → + position band → + gate block → + Schmitt →
  + monthly gate (= chosen).
- **One-at-a-time**: each knob alone on the L1 baseline.
- **Sensitivity**: softmax τ ∈ {0.5, 1, 2} in place of equal weight in the chosen config, with
  effective N (1/Σw²) and average cash from the 35% cap.
- **Reference**: the chosen config with the macro gate disabled.

Reported per row: CAGR, Sharpe, max drawdown, annual turnover and turnover by cause, costs as %
of final equity, average held rank, gate transitions per year, average cash. Nothing is promoted
from the sensitivity or ablation rows into the chosen config after the run.

## Measurement changes (not parameters)

- 2026-09-15 — **Annualization on the market calendar.** Layer 1 annualized every metric over
  the master calendar (NYSE ∪ KRX sessions), so the 12-stock control counted 12.03 "years" of
  252 days over a window in which the ETF universe (NYSE only) counts 11.67, and USD names
  carried 91 zero-return days. Metrics, drawdowns, rolling statistics and the attribution
  year count now use the primary exchange's sessions for every run (`BacktestResult.
  market_sessions`), which is a no-op for single-calendar universes. The engine, targets and
  trades are unchanged (golden test). Effect on the Layer 1 baseline of the control: CAGR
  37.1% → ~38.5%, all benchmarks likewise; the README restates the numbers on the new basis.
  Reason: the selection-bias comparison requires the same year definition on both universes.

- 2026-09-17 — **Idle cash earns the T-bill rate.** Layer 1 and brief v2 credited uninvested cash with 0%. `backtest.cash_earns_rf: true` (all four configs, every study row) compounds the cash balance at `DTB3` × calendar days since the previous session / 365 at the start of each session, for the strategy and every benchmark run through the same engine. The rate is the one-session-lagged macro series already used for Sharpe, so there is no lookahead; sessions without a published rate accrue nothing. Calendar-day accrual keeps the credit independent of the master calendar (a 1/252-per-session rule would credit the NYSE ∪ KRX basket ~3% more than the NYSE-only ETF control). The neutral default is `false` and byte-identical to Layer 1 (golden test). Effect on the basket run is recorded in the commit that regenerates `outputs/`. Reason: IMPROVEMENTS.md §2.1 — the trade-vs-hold verdict compares an overlay that holds cash against a fully invested basket, so the cash must earn its true alternative.

- 2026-09-17 — **Dead scaffolding removed.** `sizing.house_money` (a flag whose only effect was a log line saying the rule is not implemented), the `ml` config block and `ranker.method: ml` (a `NotImplementedError` branch) and `risk.monte_carlo_runs` (never read) are deleted from the schema and the configs. The former parameter-table row for `sizing.house_money.enabled` is gone with it. No run, target, trade or metric changes (golden test). Reason: IMPROVEMENTS.md §3.

## Deviations

None. (Format: date — parameter — old → new — reason — run that motivated it.)
