"""Macro gate (SPEC §1C): a scalar exposure multiplier in ``[min_exposure, 1.0]`` per date.

Three sub-gates each produce a factor (1.0 = risk-on, ``*_scale_factor`` = risk-off) from the
lagged macro features; they are combined per ``config.macro_gate.combination`` and clipped.
A NaN input fails open (factor 1.0) for that sub-gate. Pure function; no state.
"""

from __future__ import annotations

import logging

import pandas as pd

from thematic_alpha.config import MacroGateConfig

logger = logging.getLogger("thematic_alpha.strategy.macro_gate")


def _factor(signal: pd.Series, threshold: float, scale: float, name: str) -> pd.Series:
    n_nan = int(signal.isna().sum())
    if n_nan:
        logger.warning("%s gate: %d dates have no input; failing open (factor=1).", name, n_nan)
    return pd.Series(1.0, index=signal.index).where(~(signal > threshold), scale).rename(name)


def gate_factors(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> pd.DataFrame:
    """Per-date sub-gate factors plus the combined, clipped ``exposure`` column."""
    yield_col = f"dgs10_chg_{cfg.yield_change_window}d"
    oil_col = f"wti_chg_{cfg.oil_change_window}d"
    for col in ("vix_level", yield_col, oil_col):
        if col not in macro_feats.columns:
            raise ValueError(f"macro features lack {col!r}, required by the macro gate")

    out = pd.DataFrame(index=macro_feats.index)
    out["vix_factor"] = _factor(
        macro_feats["vix_level"], cfg.vix_threshold, cfg.vix_scale_factor, "vix"
    )
    out["yield_factor"] = _factor(
        macro_feats[yield_col], cfg.yield_change_threshold, cfg.yield_scale_factor, "yield"
    )
    out["oil_factor"] = _factor(
        macro_feats[oil_col], cfg.oil_change_threshold, cfg.oil_scale_factor, "oil"
    )
    factors = out[["vix_factor", "yield_factor", "oil_factor"]]
    if cfg.combination == "multiplicative":
        combined = factors.prod(axis=1)
    elif cfg.combination == "min":
        combined = factors.min(axis=1)
    else:  # average
        combined = factors.mean(axis=1)
    out["exposure"] = combined.clip(lower=cfg.min_exposure, upper=1.0)
    if not cfg.enabled:
        out["exposure"] = 1.0
    return out


def compute_exposure(macro_feats: pd.DataFrame, cfg: MacroGateConfig) -> pd.Series:
    return gate_factors(macro_feats, cfg)["exposure"].rename("exposure")
