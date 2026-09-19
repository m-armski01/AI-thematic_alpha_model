"""Performance and risk metrics (SPEC §1E). Every figure is net of the costs the engine charged.

Conventions: 252 periods per year on the **market calendar** (``BacktestResult.market_sessions``,
the primary exchange's sessions, so a NYSE ∪ KRX master calendar does not inflate the year
count); the risk-free rate is ``DTB3`` (annual %, discount basis — close enough for Sharpe)
turned into a daily rate; Sortino uses downside deviation with MAR = 0; VaR/CVaR are positive
numbers meaning *losses* at the daily horizon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from thematic_alpha.backtest.engine import BacktestResult
from thematic_alpha.config import RiskConfig
from thematic_alpha.risk.drawdown import max_drawdown

PERIODS = 252
# Reports do not annualise (CAGR, Calmar, alpha) over windows shorter than this: ~24 months.
MIN_ANNUALISE_SESSIONS = 2 * PERIODS


def annualize_rf(rf_annual_pct: pd.Series) -> pd.Series:
    """DTB3 in percent per year -> simple daily rate on the same index."""
    return (rf_annual_pct / 100.0 / PERIODS).rename("rf_daily")


def cash_accrual_rates(rf_annual_pct: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """Per-session simple rate earned on idle cash: annual % x calendar days since the previous
    session / 365. Calendar days (not a 1/252 session count) so the accrual does not depend on
    which exchanges' sessions the engine iterates over. The first session and any session
    without a published rate accrue 0; nothing is back-filled."""
    dates = pd.DatetimeIndex(dates)
    rf = rf_annual_pct.reindex(dates).to_numpy(dtype=float) / 100.0
    days = dates.to_series().diff().dt.days.fillna(0.0).to_numpy(dtype=float)
    return pd.Series(np.nan_to_num(rf * days / 365.0), index=dates, name="cash_rate")


def cagr(equity: pd.Series, initial: float) -> float:
    years = len(equity) / PERIODS
    return float((equity.iloc[-1] / initial) ** (1.0 / years) - 1.0) if years > 0 else 0.0


def sharpe(excess: pd.Series) -> float:
    sd = excess.std(ddof=1)
    return float(excess.mean() / sd * np.sqrt(PERIODS)) if sd > 0 else float("nan")


def sortino(returns: pd.Series, excess: pd.Series, mar: float = 0.0) -> float:
    downside = np.minimum(returns - mar, 0.0)
    dd = float(np.sqrt(np.mean(downside**2)))
    return float(excess.mean() / dd * np.sqrt(PERIODS)) if dd > 0 else float("nan")


def historical_var(returns: pd.Series, confidence: float) -> float:
    return float(-np.quantile(returns, 1.0 - confidence))


def parametric_var(returns: pd.Series, confidence: float) -> float:
    from statistics import NormalDist

    z = NormalDist().inv_cdf(1.0 - confidence)
    return float(-(returns.mean() + z * returns.std(ddof=1)))


def cvar(returns: pd.Series, confidence: float) -> float:
    threshold = -historical_var(returns, confidence)
    tail = returns[returns <= threshold]
    return float(-tail.mean()) if len(tail) else float("nan")


def ols_alpha_beta(excess: pd.Series, market_excess: pd.Series) -> tuple[float, float, float]:
    """Full-sample OLS of daily excess returns on market excess returns.

    Returns (alpha annualized, beta, t-statistic of the daily alpha under homoskedastic OLS
    standard errors). Daily returns of a weekly-rebalanced book are close to serially
    uncorrelated, so the plain standard error is a fair first-order measure of significance.
    """
    df = pd.concat([excess, market_excess], axis=1, keys=["y", "x"]).dropna()
    if len(df) < 3:
        return float("nan"), float("nan"), float("nan")
    y = df["y"].to_numpy()
    x = np.column_stack([np.ones(len(df)), df["x"].to_numpy()])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ coef
    sigma2 = float(resid @ resid) / (len(df) - 2)
    # pinv: a constant market series (zero variance) must not raise, it just has no beta.
    se_alpha = float(np.sqrt(max(sigma2 * np.linalg.pinv(x.T @ x)[0, 0], 0.0)))
    tstat = float(coef[0] / se_alpha) if se_alpha > 0 else float("nan")
    return float(coef[0] * PERIODS), float(coef[1]), tstat


def annualisable(metrics: dict) -> bool:
    """Whether a metrics dict covers enough sessions for annualised figures to be reported."""
    return int(metrics.get("n_days", 0)) >= MIN_ANNUALISE_SESSIONS


def rolling_beta(returns: pd.Series, market: pd.Series, window: int) -> pd.Series:
    cov = returns.rolling(window, min_periods=window).cov(market)
    var = market.rolling(window, min_periods=window).var()
    return (cov / var).rename(f"beta_{window}d")


def rolling_sharpe(excess: pd.Series, window: int = PERIODS) -> pd.Series:
    mean = excess.rolling(window, min_periods=window).mean()
    sd = excess.rolling(window, min_periods=window).std(ddof=1)
    return (mean / sd * np.sqrt(PERIODS)).rename(f"sharpe_{window}d")


def period_returns(equity: pd.Series, execution_dates: pd.DatetimeIndex) -> pd.Series:
    """Equity return between consecutive rebalances (execution date to next execution date)."""
    dates = execution_dates[execution_dates.isin(equity.index)]
    if len(dates) < 2:
        return pd.Series(dtype=float)
    marks = equity.loc[dates]
    return marks.pct_change().dropna()


def compute_metrics(
    result: BacktestResult,
    rf_daily: pd.Series,
    market_returns: pd.Series,
    cfg: RiskConfig,
    period_dates: pd.DatetimeIndex | None = None,
) -> dict:
    """``period_dates`` defines the rebalance periods for hit rate / avg win / avg loss.

    Pass the strategy's execution schedule for every run so buy-and-hold benchmarks (which
    trade only a handful of times) are measured over the same weekly periods.
    """
    equity, r = result.on_market_calendar()
    rf = rf_daily.reindex(r.index).ffill().fillna(0.0)
    excess = r - rf
    mkt = market_returns.reindex(r.index)
    mkt_excess = mkt - rf
    years = len(r) / PERIODS
    mdd = max_drawdown(equity)
    dates = period_dates if period_dates is not None else result.execution_dates
    per = period_returns(equity, dates)
    wins, losses = per[per > 0], per[per < 0]
    alpha, beta, alpha_t = ols_alpha_beta(excess, mkt_excess)

    out: dict = {
        "total_return": float(equity.iloc[-1] / result.initial_capital - 1.0),
        "cagr": cagr(equity, result.initial_capital),
        "ann_vol": float(r.std(ddof=1) * np.sqrt(PERIODS)),
        "sharpe": sharpe(excess),
        "sortino": sortino(r, excess),
        "max_drawdown": mdd["depth"],
        "max_drawdown_peak": mdd["peak"],
        "max_drawdown_trough": mdd["trough"],
        "max_drawdown_recovery": mdd["recovery"],
        "max_drawdown_duration_days": mdd["duration_days"],
        "calmar": (
            float(cagr(equity, result.initial_capital) / abs(mdd["depth"]))
            if mdd["depth"] < 0
            else float("nan")
        ),
        "alpha_ann": alpha,
        "alpha_tstat": alpha_t,
        "beta": beta,
        "hit_rate": float((per > 0).mean()) if len(per) else float("nan"),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "n_periods": int(len(per)),
        "ann_turnover": float(result.turnover_series.sum() / years) if years > 0 else 0.0,
        "total_costs": result.total_costs,
        "costs_pct_final_equity": float(result.total_costs / result.final_equity),
        "excess_kurtosis": float(r.kurt()),
        "n_days": int(len(r)),
        "window_months": int(round(len(r) / (PERIODS / 12))),
    }
    for c in cfg.var_confidence:
        tag = f"{int(round(c * 100))}"
        out[f"var_hist_{tag}"] = historical_var(r, c)
        out[f"var_param_{tag}"] = parametric_var(r, c)
    out["cvar_95"] = cvar(r, 0.95)
    return out


def fx_contribution(base: BacktestResult, local: BacktestResult) -> dict:
    """Base-currency minus local-currency performance of the *same* target weights."""
    eq_base, _ = base.on_market_calendar()
    eq_local, _ = local.on_market_calendar()
    return {
        "total_return_base": float(base.final_equity / base.initial_capital - 1.0),
        "total_return_local": float(local.final_equity / local.initial_capital - 1.0),
        "cagr_base": cagr(eq_base, base.initial_capital),
        "cagr_local": cagr(eq_local, local.initial_capital),
        "fx_contribution_total": float(
            (base.final_equity - local.final_equity) / base.initial_capital
        ),
        "fx_contribution_cagr": cagr(eq_base, base.initial_capital)
        - cagr(eq_local, local.initial_capital),
    }
