"""Performance by regime (IMPROVEMENTS §2.2).

The overlay is a macro-timing thesis, so it is tested where it claims to help: every market
session is tagged by the state the gate could see on that day, and the overlay is compared with
equal-weight buy-and-hold inside each bucket. Three tags, all pure functions of history:

- ``vix``: calm (below the release level), elevated (between release and engage), stress (above
  the engage level) on the lagged VIX level the gate itself reads;
- ``gate``: risk-off / risk-on, the state the book was actually subjected to (signal-date state
  carried forward to the next signal date; risk-on before the first signal date);
- ``rates``: rate shock / no shock on the lagged N-day change in the 10-year yield against the
  gate's engage threshold.

Bucket statistics are computed on the concatenated bucket sessions: total return is the compound
return of those sessions, the worst drawdown is measured on that concatenated path (not on the
calendar), and an annualised return is reported only when the bucket holds at least
``MIN_ANNUALISE_SESSIONS`` sessions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from thematic_alpha.risk.metrics import MIN_ANNUALISE_SESSIONS, PERIODS

VIX_CALM_DEFAULT = 20.0  # used when the gate has no release threshold (Layer 1 neutral)
VIX_LABELS = ["calm", "elevated", "stress"]
GATE_LABELS = ["risk-on", "risk-off"]
RATE_LABELS = ["no shock", "rate shock"]
DIMENSIONS = {"vix": VIX_LABELS, "gate": GATE_LABELS, "rates": RATE_LABELS}
STAT_COLUMNS = [
    "n_sessions",
    "share",
    "total_return",
    "ann_return",
    "ann_vol",
    "hit_rate",
    "max_drawdown",
]


def vix_regime(vix: pd.Series, calm: float, stress: float) -> pd.Series:
    """calm: vix < calm; elevated: calm <= vix <= stress; stress: vix > stress; NaN stays NaN."""
    out = pd.Series(pd.NA, index=vix.index, dtype="object")
    out[vix < calm] = "calm"
    out[(vix >= calm) & (vix <= stress)] = "elevated"
    out[vix > stress] = "stress"
    return out.rename("vix")


def gate_regime(state: pd.Series, action: str, dates: pd.DatetimeIndex) -> pd.Series:
    """Daily risk-on / risk-off from the applied signal-date state, carried forward."""
    risk_off = (state < 1.0) if action == "scale" else state.astype(bool)
    daily = risk_off.astype(float).reindex(dates).ffill().fillna(0.0).astype(bool)
    return daily.map({True: "risk-off", False: "risk-on"}).rename("gate")


def rate_regime(change: pd.Series, threshold: float) -> pd.Series:
    out = pd.Series(pd.NA, index=change.index, dtype="object")
    out[change > threshold] = "rate shock"
    out[change <= threshold] = "no shock"
    return out.rename("rates")


def tag_sessions(
    dates: pd.DatetimeIndex,
    vix: pd.Series,
    gate_state: pd.Series,
    gate_action: str,
    rate_change: pd.Series,
    *,
    vix_calm: float,
    vix_stress: float,
    rate_threshold: float,
) -> pd.DataFrame:
    """date x {vix, gate, rates} labels on ``dates``; sessions without a macro value stay NA."""
    dates = pd.DatetimeIndex(dates)
    return pd.concat(
        [
            vix_regime(vix.reindex(dates), vix_calm, vix_stress),
            gate_regime(gate_state, gate_action, dates),
            rate_regime(rate_change.reindex(dates), rate_threshold),
        ],
        axis=1,
    )


def bucket_stats(returns: pd.Series, n_total: int) -> dict:
    r = returns.dropna().to_numpy(dtype=float)
    n = len(r)
    if n == 0:
        return {
            "n_sessions": 0,
            "share": 0.0,
            "total_return": float("nan"),
            "ann_return": float("nan"),
            "ann_vol": float("nan"),
            "hit_rate": float("nan"),
            "max_drawdown": float("nan"),
        }
    path = np.cumprod(1.0 + r)
    total = float(path[-1] - 1.0)
    return {
        "n_sessions": n,
        "share": n / n_total if n_total else float("nan"),
        "total_return": total,
        "ann_return": (
            float((1.0 + total) ** (PERIODS / n) - 1.0)
            if n >= MIN_ANNUALISE_SESSIONS
            else float("nan")
        ),
        "ann_vol": float(np.std(r, ddof=1) * np.sqrt(PERIODS)) if n > 1 else float("nan"),
        "hit_rate": float((r > 0).mean()),
        "max_drawdown": float((path / np.maximum.accumulate(path) - 1.0).min()),
    }


def regime_table(returns: dict[str, pd.Series], tags: pd.Series, labels: list[str]) -> pd.DataFrame:
    """Rows = (regime, run) in the given label order; columns = ``STAT_COLUMNS``.

    ``returns`` maps run name -> daily simple returns on the market calendar; every run is
    aligned to the tag index, and the share is of tagged sessions.
    """
    tagged = tags.dropna()
    rows = {}
    for label in labels:
        dates = tagged.index[tagged == label]
        for run, r in returns.items():
            rows[(label, run)] = bucket_stats(r.reindex(dates), len(tagged))
    out = pd.DataFrame.from_dict(rows, orient="index", columns=STAT_COLUMNS)
    out.index = pd.MultiIndex.from_tuples(out.index, names=["regime", "run"])
    return out


def compute_regimes(
    returns: dict[str, pd.Series],
    dates: pd.DatetimeIndex,
    macro: pd.DataFrame,
    gate_state: pd.Series,
    gate_action: str,
    *,
    vix_calm: float,
    vix_stress: float,
    rate_column: str,
    rate_threshold: float,
) -> dict[str, pd.DataFrame]:
    """One table per dimension (``DIMENSIONS`` keys) for the runs in ``returns``."""
    tags = tag_sessions(
        dates,
        macro["vix_level"],
        gate_state,
        gate_action,
        macro[rate_column],
        vix_calm=vix_calm,
        vix_stress=vix_stress,
        rate_threshold=rate_threshold,
    )
    return {dim: regime_table(returns, tags[dim], labels) for dim, labels in DIMENSIONS.items()}
