"""Turnover attribution (brief v2, step 1): why did each trade happen?

Every trade in the engine's log is split, in units of pre-trade equity, into four causes that
sum to the traded notional exactly, so the per-run annualized turnover by cause sums to the
headline ``ann_turnover``:

* **membership** — the name is entering (not in the previous target set) or exiting (not in
  the new one). The whole trade is membership.
* otherwise the name is held→held and the change ``Δ = w_target − w_before`` is split into
  signed components that sum to Δ exactly:

  - ``drift    = w_prev_target − w_before`` (the position drifted away from its last target;
    this also absorbs the residual of any earlier trade that was skipped or scaled down for
    cash, since those leave the position away from target too),
  - ``gate     = (q_new − p_new) − (q_prev − p_prev)`` (the change in the gate's distortion of
    the pre-gate book; valid for both scale and block modes: a released block's pent-up
    increase lands here),
  - ``reweight = (w_target − w_prev_target) − gate`` (ranker, mask and cap effects).

  The actually traded notional is allocated pro-rata to the components whose sign matches Δ;
  opposing components were netted away and get 0. If every component is zero the trade is
  drift.

``p`` is the pre-gate book (after ranker + mask + normalize), ``q`` the post-gate, pre-cap book,
both on signal dates; they are mapped to the execution dates the engine actually ran. For
benchmarks ``q = p =`` their targets, so their gate component is identically zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.backtest.engine import BacktestResult
from thematic_alpha.risk.metrics import PERIODS

CAUSES = ["membership", "drift", "gate", "reweight"]


def _on_execution_dates(
    frame: pd.DataFrame, signal_to_execution: pd.Series, tickers: list[str]
) -> pd.DataFrame:
    """A signal-date frame restricted to executed signals and re-dated to execution dates."""
    out = frame.reindex(index=signal_to_execution.index, columns=tickers).fillna(0.0)
    out.index = pd.DatetimeIndex(signal_to_execution.to_numpy())
    return out


def gate_change(
    p: pd.DataFrame, q: pd.DataFrame, signal_to_execution: pd.Series, tickers: list[str]
) -> pd.DataFrame:
    """``(q_new − p_new) − (q_prev − p_prev)`` per executed date, prev = previous executed row."""
    distortion = _on_execution_dates(q, signal_to_execution, tickers) - _on_execution_dates(
        p, signal_to_execution, tickers
    )
    return distortion - distortion.shift(1).fillna(0.0)


def attribute_trades(result: BacktestResult, p: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    """Per-trade attribution frame: the engine's trade columns plus, in weight units, the traded
    amount, the signed components and the allocated causes (which sum to ``traded``)."""
    tr = result.trades.copy()
    cols = [*CAUSES, "delta", "traded"]
    if tr.empty:
        return tr.assign(**{c: pd.Series(dtype=float) for c in cols})
    if result.signal_to_execution is None:
        raise ValueError("BacktestResult lacks signal_to_execution; rerun the engine")
    tickers = list(result.weights_history.columns)
    gc = gate_change(p, q, result.signal_to_execution, tickers).stack()
    keys = pd.MultiIndex.from_arrays([tr["date"], tr["ticker"]])
    g = gc.reindex(keys).fillna(0.0).to_numpy()

    w_before = tr["w_before"].to_numpy()
    w_target = tr["w_target"].to_numpy()
    w_prev = tr["w_prev_target"].to_numpy()
    delta = w_target - w_before
    traded = (tr["notional"] / tr["equity_pre"]).to_numpy()
    membership_trade = (w_prev == 0.0) | (w_target == 0.0)

    raw = pd.DataFrame(index=tr.index, columns=CAUSES, dtype=float)
    raw["membership"] = np.where(membership_trade, delta, 0.0)
    raw["drift"] = np.where(membership_trade, 0.0, w_prev - w_before)
    raw["gate"] = np.where(membership_trade, 0.0, g)
    raw["reweight"] = np.where(membership_trade, 0.0, (w_target - w_prev) - g)

    sign = np.sign(delta)[:, None]
    matched = raw.where((np.sign(raw.to_numpy()) == sign) & (raw != 0.0), 0.0)
    denom = matched.sum(axis=1).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(denom[:, None] != 0.0, matched.to_numpy() / denom[:, None], 0.0)
    alloc = share * traded[:, None]
    fallback = denom == 0.0
    alloc[fallback] = 0.0
    alloc[fallback, CAUSES.index("drift")] = traded[fallback]

    out = tr
    for i, c in enumerate(CAUSES):
        out[f"{c}_raw"] = raw[c].to_numpy()
        out[c] = alloc[:, i]
    out["delta"] = delta
    out["traded"] = traded
    return out


def years_of(result: BacktestResult) -> float:
    return len(result.daily_returns) / PERIODS


def turnover_by_cause(attributed: pd.DataFrame, years: float) -> pd.Series:
    """Annualized turnover per cause plus ``total``; ``total`` equals the metrics' ann_turnover."""
    sums = attributed[CAUSES].sum() if len(attributed) else pd.Series(0.0, index=CAUSES)
    out = (sums / years) if years > 0 else sums * 0.0
    out["total"] = out[CAUSES].sum()
    return out.astype(float)


@dataclass
class GateDiagnostics:
    n_transitions: int
    per_year: float
    reversed_within_1: int
    reversed_within_2: int
    n_dates: int

    def as_dict(self) -> dict:
        return {
            "n_transitions": self.n_transitions,
            "per_year": self.per_year,
            "reversed_within_1": self.reversed_within_1,
            "reversed_within_2": self.reversed_within_2,
            "n_dates": self.n_dates,
        }


def gate_diagnostics(state: pd.Series, years: float) -> GateDiagnostics:
    """Transitions of the applied gate state over signal dates, and how many of them reverse
    (return to the pre-transition value) within 1 and within 2 signal dates."""
    s = state.to_numpy()
    n = len(s)
    trans = [i for i in range(1, n) if s[i] != s[i - 1]]
    rev1 = sum(1 for i in trans if i + 1 < n and s[i + 1] == s[i - 1])
    rev2 = sum(1 for i in trans if any(i + k < n and s[i + k] == s[i - 1] for k in (1, 2)))
    return GateDiagnostics(
        n_transitions=len(trans),
        per_year=len(trans) / years if years > 0 else 0.0,
        reversed_within_1=rev1,
        reversed_within_2=rev2,
        n_dates=n,
    )
