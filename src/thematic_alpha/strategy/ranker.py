"""Ranker (SPEC §1C): target weights per date from the feature panel.

``momentum_zscore``: z-score ``mom_63`` across *eligible* names, select ``top_n``, weight per
``weighting``: ``equal``, ``inverse_vol``, ``conviction_tier`` by rank, or ``softmax`` over the
selected names' z-scores with temperature τ, ``w_i = exp((z_i − max z) / τ) / Σ``
(shift-invariant, defined for any real z, no clipping). Tickers failing ``min_history_days`` are
already ineligible (features/build.py), so they never enter the cross-section, and weights
renormalize over the survivors. Rows with no eligible name get zero weight (cash).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from thematic_alpha.config import RankerConfig

SIGNAL = "mom_63"
VOL = "vol_21"


def zscore_rows(values: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score over eligible names; a single-name row scores 0."""
    v = values.where(eligible)
    mean = v.mean(axis=1)
    std = v.std(axis=1, ddof=0)
    z = v.sub(mean, axis=0).div(std.replace(0.0, np.nan), axis=0)
    return z.fillna(0.0).where(eligible)


def select_top_n(score: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Rank position (1 = best) for the top_n names per row, NaN elsewhere. Ties: column order."""
    order = score.rank(axis=1, ascending=False, method="first")
    return order.where(order <= top_n)


def softmax_rows(score: pd.DataFrame, selected: pd.DataFrame, temperature: float) -> pd.DataFrame:
    """Row-wise softmax of ``score`` over ``selected`` names, stabilised by the row maximum."""
    z = score.where(selected)
    shifted = z.sub(z.max(axis=1), axis=0) / temperature
    return np.exp(shifted).fillna(0.0)


def weight_selected(
    position: pd.DataFrame,
    weighting: str,
    tiers: list[float],
    vol: pd.DataFrame | None = None,
    score: pd.DataFrame | None = None,
    temperature: float = 1.0,
) -> pd.DataFrame:
    selected = position.notna()
    if weighting == "equal":
        raw = selected.astype(float)
    elif weighting == "softmax":
        if score is None:
            raise ValueError("softmax weighting needs the score frame")
        raw = softmax_rows(score, selected, temperature)
    elif weighting == "inverse_vol":
        if vol is None:
            raise ValueError("inverse_vol weighting needs a vol frame")
        raw = (1.0 / vol).where(selected).fillna(0.0)
    elif weighting == "conviction_tier":
        tier_arr = np.asarray(tiers, dtype=float)
        idx = position.fillna(0).astype(int).to_numpy() - 1  # -1 where not selected
        raw = pd.DataFrame(
            np.where(idx >= 0, tier_arr[np.clip(idx, 0, len(tier_arr) - 1)], 0.0),
            index=position.index,
            columns=position.columns,
        )
    else:  # pragma: no cover - guarded by the config Literal
        raise ValueError(f"unknown weighting {weighting!r}")
    total = raw.sum(axis=1)
    return raw.div(total.replace(0.0, np.nan), axis=0).fillna(0.0)


def rank(wide: dict[str, pd.DataFrame], eligible: pd.DataFrame, cfg: RankerConfig) -> pd.DataFrame:
    """date x ticker weights summing to 1 on each date with at least one eligible name."""
    if cfg.method == "ml":
        raise NotImplementedError("ranker.method='ml' arrives in Layer 2")
    if cfg.method == "equal_weight":
        return weight_selected(eligible.astype(float).where(eligible), "equal", [])
    score = zscore_rows(wide[SIGNAL], eligible)
    position = select_top_n(score, cfg.top_n)
    return weight_selected(
        position,
        cfg.weighting,
        cfg.conviction_tiers,
        wide.get(VOL),
        score,
        cfg.softmax_temperature,
    )


def naive_momentum(
    wide: dict[str, pd.DataFrame], eligible: pd.DataFrame, top_n: int
) -> pd.DataFrame:
    """Benchmark 3 (SPEC §1D): equal-weight top-N by mom_63, no gate, no mask."""
    position = select_top_n(wide[SIGNAL].where(eligible), top_n)
    return weight_selected(position, "equal", [])
