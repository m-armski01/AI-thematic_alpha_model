"""Macro gate (SPEC §1C, brief v2 decision 4).

Three sub-gates (VIX level, 21-day 10y-yield change, 21-day WTI change) each produce an
*engaged* boolean from the lagged macro features. What happens next depends on
``macro_gate.action``:

* ``scale`` (Layer 1): each engaged sub-gate contributes its ``*_scale_factor``; the factors are
  combined per ``combination`` and clipped to ``[min_exposure, 1]`` into a scalar exposure
  multiplier per date.
* ``block_increases``: the gate is the boolean ``risk_off = any sub-gate engaged``; the book is
  not scaled, non-exempt names simply cannot increase (see ``compose``). The scale factors and
  ``min_exposure`` are unused in this mode.

Each sub-gate is a Schmitt trigger: it engages when its signal is *above* the engage threshold
and releases only when the signal is *at or below* the release threshold; in between it keeps
its previous state. With release == engage (the neutral default) there is no dead band and the
trigger is exactly the Layer 1 comparator ``signal > threshold``. A NaN input fails open
(released) for that sub-gate on that date, with a log line. Everything here is a pure function
of history on the daily feature index; ``applied_gate`` samples it on signal dates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.config import MacroGateConfig

logger = logging.getLogger("thematic_alpha.strategy.macro_gate")

SUBGATES = ("vix", "yield", "oil")


def schmitt(signal: pd.Series, engage: float, release: float) -> pd.Series:
    """Stateful comparator: True above ``engage``, False at or below ``release``, previous state
    in between; NaN -> False (fail open). Runs forward in time only."""
    x = signal.to_numpy(dtype=float)
    out = np.zeros(len(x), dtype=bool)
    state = False
    for i, v in enumerate(x):
        if np.isnan(v):
            state = False
        elif v > engage:
            state = True
        elif v <= release:
            state = False
        out[i] = state
    return pd.Series(out, index=signal.index)


def _engaged(signal: pd.Series, engage: float, release: float, name: str) -> pd.Series:
    n_nan = int(signal.isna().sum())
    if n_nan:
        logger.warning("%s gate: %d dates have no input; failing open (released).", name, n_nan)
    return schmitt(signal, engage, release).rename(f"{name}_engaged")


def _inputs(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> dict[str, pd.Series]:
    cols = {
        "vix": "vix_level",
        "yield": f"dgs10_chg_{cfg.yield_change_window}d",
        "oil": f"wti_chg_{cfg.oil_change_window}d",
    }
    for col in cols.values():
        if col not in macro_feats.columns:
            raise ValueError(f"macro features lack {col!r}, required by the macro gate")
    return {k: macro_feats[c] for k, c in cols.items()}


def engaged_states(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> pd.DataFrame:
    """Per-date engaged booleans for the three sub-gates (daily, pure function of history)."""
    x = _inputs(macro_feats, cfg)
    thresholds = {
        "vix": cfg.vix_threshold,
        "yield": cfg.yield_change_threshold,
        "oil": cfg.oil_change_threshold,
    }
    return pd.DataFrame(
        {
            f"{k}_engaged": _engaged(x[k], thresholds[k], cfg.release_threshold(k), k)
            for k in SUBGATES
        }
    )


def gate_factors(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> pd.DataFrame:
    """Per-date sub-gate factors, the combined clipped ``exposure`` and the boolean ``risk_off``."""
    engaged = engaged_states(macro_feats, cfg)
    scales = {
        "vix": cfg.vix_scale_factor,
        "yield": cfg.yield_scale_factor,
        "oil": cfg.oil_scale_factor,
    }
    out = pd.DataFrame(index=macro_feats.index)
    for k in SUBGATES:
        out[f"{k}_factor"] = (
            pd.Series(1.0, index=macro_feats.index)
            .where(~engaged[f"{k}_engaged"], scales[k])
            .rename(f"{k}_factor")
        )
    factors = out[[f"{k}_factor" for k in SUBGATES]]
    if cfg.combination == "multiplicative":
        combined = factors.prod(axis=1)
    elif cfg.combination == "min":
        combined = factors.min(axis=1)
    else:  # average
        combined = factors.mean(axis=1)
    out["exposure"] = combined.clip(lower=cfg.min_exposure, upper=1.0)
    out["risk_off"] = engaged.any(axis=1)
    for k in SUBGATES:
        out[f"{k}_engaged"] = engaged[f"{k}_engaged"]
    if not cfg.enabled:
        out["exposure"] = 1.0
        out["risk_off"] = False
    return out


def compute_exposure(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> pd.Series:
    return gate_factors(macro_feats, cfg)["exposure"].rename("exposure")


@dataclass
class GateState:
    """The gate as applied on signal dates."""

    action: str  # "scale" | "block_increases"
    exposure: pd.Series  # signal_date -> multiplier (1.0 throughout in block mode)
    risk_off: pd.Series  # signal_date -> bool (False throughout in scale mode)
    evaluated: pd.Series  # signal_date -> True where the daily gate was sampled

    @property
    def state(self) -> pd.Series:
        """The applied state for diagnostics: exposure (scale) or risk-off (block)."""
        return self.exposure if self.action == "scale" else self.risk_off


def applied_gate(
    gate_daily: pd.DataFrame, signal_dates: pd.DatetimeIndex, cfg: MacroGateConfig
) -> GateState:
    """Sample the daily gate on every signal date."""
    exposure = gate_daily["exposure"].reindex(signal_dates).fillna(1.0).rename("exposure")
    risk_off = gate_daily["risk_off"].reindex(signal_dates).fillna(False).astype(bool)
    evaluated = pd.Series(True, index=signal_dates, name="evaluated")
    if cfg.action == "scale":
        risk_off = pd.Series(False, index=signal_dates, name="risk_off")
    else:
        exposure = pd.Series(1.0, index=signal_dates, name="exposure")
    return GateState(
        action=cfg.action,
        exposure=exposure,
        risk_off=risk_off.rename("risk_off"),
        evaluated=evaluated,
    )
