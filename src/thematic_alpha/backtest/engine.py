"""Custom backtest engine (SPEC §1D, §3.1).

Holdings are tracked in shares and cash. Between rebalances nothing is touched, so weights drift
with prices. A target-weight row dated ``s`` (a signal date) is executed ``execution_lag_days``
primary-exchange sessions later at ``execution_price`` (open or close). Costs are charged on
traded notional and paid from cash; buys are scaled down so cash never goes negative. No
leverage, no shorting.

Approximation (documented): if a ticker's own exchange is closed on an execution date, it trades
at its forward-filled price. A ticker whose price is NaN (not yet listed / real gap) cannot be
traded that day; its target weight is left in cash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.backtest.costs import cost_rate, flat_fee, transaction_cost
from thematic_alpha.config import BacktestConfig, CostsConfig

logger = logging.getLogger("thematic_alpha.backtest.engine")

EPS = 1e-12
NOISE = 1e-9  # trades smaller than this fraction of equity are float noise, not decisions


@dataclass
class BacktestResult:
    equity_curve: pd.Series  # daily, base currency
    daily_returns: pd.Series  # daily simple returns (first day vs initial capital)
    weights_history: pd.DataFrame  # daily date x ticker, post-close drifted weights
    trades: pd.DataFrame  # one row per (execution date, ticker) with nonzero notional
    turnover_series: pd.Series  # per execution date: traded notional / pre-trade equity
    costs_paid: pd.Series  # per execution date, base currency
    cash: pd.Series  # daily
    initial_capital: float
    execution_dates: pd.DatetimeIndex

    @property
    def total_costs(self) -> float:
        return float(self.costs_paid.sum())

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1])


def execution_dates(
    signal_dates: pd.DatetimeIndex, sessions: pd.DatetimeIndex, lag: int
) -> pd.Series:
    """Map each signal date to the session ``lag`` sessions later (dropping any past the end)."""
    sessions = pd.DatetimeIndex(sessions)
    pos = sessions.searchsorted(signal_dates, side="left") + lag
    keep = pos < len(sessions)
    return pd.Series(sessions[pos[keep]], index=signal_dates[keep])


def run_backtest(
    prices_close: pd.DataFrame,
    target_weights: pd.DataFrame,
    config: BacktestConfig,
    costs: CostsConfig,
    prices_open: pd.DataFrame | None = None,
    sessions: pd.DatetimeIndex | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> BacktestResult:
    px_close = prices_close.sort_index()
    tickers = list(px_close.columns)
    if sessions is None:
        sessions = px_close.index
    if config.execution_price == "open":
        if prices_open is None:
            raise ValueError("execution_price='open' requires prices_open")
        px_exec_all = prices_open.reindex(index=px_close.index, columns=tickers)
    else:
        px_exec_all = px_close

    tw = target_weights.reindex(columns=tickers).fillna(0.0).sort_index()
    if (tw.sum(axis=1) > 1.0 + 1e-9).any() or (tw < 0).any().any():
        raise ValueError("target weights must be >= 0 and sum to <= 1 on every date")
    exec_map = execution_dates(tw.index, sessions, config.execution_lag_days)
    targets = tw.loc[exec_map.index].set_index(pd.DatetimeIndex(exec_map.to_numpy()))
    targets = targets[~targets.index.duplicated(keep="last")]

    first = pd.Timestamp(start) if start is not None else targets.index.min()
    dates = px_close.index[px_close.index >= first]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    close_ff = px_close.ffill().loc[dates].to_numpy(dtype=float)
    px_exec = px_exec_all.loc[dates].to_numpy(dtype=float)
    exec_rows = {d: targets.loc[d].to_numpy(dtype=float) for d in targets.index if d in dates}

    n = len(tickers)
    shares = np.zeros(n)
    cash = float(config.initial_capital)
    equity = np.zeros(len(dates))
    cash_hist = np.zeros(len(dates))
    weights = np.zeros((len(dates), n))
    turnover: dict[pd.Timestamp, float] = {}
    paid: dict[pd.Timestamp, float] = {}
    trade_rows: list[dict] = []
    skipped = 0

    for i, d in enumerate(dates):
        if d in exec_rows:
            px = px_exec[i]
            tradable = np.isfinite(px)
            val_px = np.where(tradable, px, np.where(np.isfinite(close_ff[i]), close_ff[i], 0.0))
            equity_pre = cash + float(shares @ val_px)
            w = exec_rows[d].copy()
            if (w[~tradable] > 0).any():
                skipped += int((w[~tradable] > 0).sum())
                w[~tradable] = 0.0
            current = np.where(tradable, shares * np.where(tradable, px, 0.0), 0.0)
            delta = np.where(tradable, w * equity_pre - current, 0.0)
            # Ignore float-noise "trades" (relative to equity) so a hold really is a hold.
            delta[np.abs(delta) < NOISE * max(equity_pre, 1.0)] = 0.0
            buys, sells = delta[delta > 0].sum(), -delta[delta < 0].sum()
            n_changed = int((delta != 0).sum())
            cost = transaction_cost(buys + sells, n_changed, costs)
            if buys > cash + sells - cost:
                # Scale buys so that cash + sells - buys - cost(buys, sells) == 0 exactly:
                # buys = (cash + sells * (1 - r) - flat) / (1 + r), r = proportional rate.
                r = cost_rate(costs)
                flat = flat_fee(n_changed, costs)
                affordable = max((cash + sells * (1.0 - r) - flat) / (1.0 + r), 0.0)
                delta[delta > 0] *= affordable / buys
                delta[np.abs(delta) < NOISE * max(equity_pre, 1.0)] = 0.0
                buys = delta[delta > 0].sum()
                n_changed = int((delta != 0).sum())
                cost = transaction_cost(buys + sells, n_changed, costs)
            share_delta = np.where(tradable, delta / np.where(tradable, px, 1.0), 0.0)
            shares = shares + share_delta
            shares[np.abs(shares) < EPS] = 0.0
            cash = cash + sells - buys - cost
            if cash < -1e-6:
                raise AssertionError(f"cash went negative on {d.date()}: {cash}")
            cash = max(cash, 0.0)
            turnover[d] = (buys + sells) / equity_pre if equity_pre > 0 else 0.0
            paid[d] = cost
            for j in np.flatnonzero(delta != 0):
                trade_rows.append(
                    {
                        "date": d,
                        "ticker": tickers[j],
                        "side": "buy" if delta[j] > 0 else "sell",
                        "shares": share_delta[j],
                        "price": px[j],
                        "notional": abs(delta[j]),
                    }
                )
        held_value = np.where(np.isfinite(close_ff[i]), shares * close_ff[i], 0.0)
        equity[i] = cash + held_value.sum()
        cash_hist[i] = cash
        weights[i] = held_value / equity[i] if equity[i] > 0 else 0.0

    if skipped:
        logger.warning(
            "%d target weights fell on untradeable (NaN-price) days; left in cash.", skipped
        )

    equity_s = pd.Series(equity, index=dates, name="equity")
    prev = np.concatenate([[config.initial_capital], equity[:-1]])
    daily_ret = pd.Series(equity / prev - 1.0, index=dates, name="ret")
    trades = pd.DataFrame(
        trade_rows, columns=["date", "ticker", "side", "shares", "price", "notional"]
    )
    exec_idx = pd.DatetimeIndex(list(turnover))
    return BacktestResult(
        equity_curve=equity_s,
        daily_returns=daily_ret,
        weights_history=pd.DataFrame(weights, index=dates, columns=tickers),
        trades=trades,
        turnover_series=pd.Series(turnover, dtype=float).reindex(exec_idx).fillna(0.0),
        costs_paid=pd.Series(paid, dtype=float).reindex(exec_idx).fillna(0.0),
        cash=pd.Series(cash_hist, index=dates, name="cash"),
        initial_capital=float(config.initial_capital),
        execution_dates=exec_idx,
    )
