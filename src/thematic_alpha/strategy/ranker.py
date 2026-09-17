"""Ranker (SPEC §1C): target weights per date from the feature panel.

``momentum_zscore``: z-score ``mom_63`` across *eligible* names, select ``top_n``, weight per
``weighting``: ``equal``, ``inverse_vol``, ``conviction_tier`` by rank, or ``softmax`` over the
selected names' z-scores with temperature τ, ``w_i = exp((z_i − max z) / τ) / Σ``
(shift-invariant, defined for any real z, no clipping). Tickers failing ``min_history_days`` are
already ineligible (features/build.py), so they never enter the cross-section, and weights
renormalize over the survivors. Rows with no eligible name get zero weight (cash).

Hysteresis (``exit_rank > top_n``): selection becomes stateful over *signal dates*. On each
signal date, incumbents that are still eligible with rank <= ``exit_rank`` are kept; the
``top_n − kept`` vacancies are filled with the best-ranked non-held names with rank <= ``top_n``.
The book never holds more than ``top_n`` names, and a strong newcomer cannot displace an adequate
incumbent, so the average cross-sectional rank of the held names is returned as a diagnostic
(plain top-N gives (1 + ... + top_n) / top_n by construction, 3.0 for top 5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from thematic_alpha.config import RankerConfig

DEFAULT_SIGNAL = "mom_63"  # Layer 1 ranking signal; the config knob is ranker.momentum_signal
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
    if cfg.method == "equal_weight":
        return weight_selected(eligible.astype(float).where(eligible), "equal", [])
    score = zscore_rows(wide[cfg.momentum_signal], eligible)
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
    wide: dict[str, pd.DataFrame],
    eligible: pd.DataFrame,
    top_n: int,
    signal: str = DEFAULT_SIGNAL,
) -> pd.DataFrame:
    """Benchmark 3 (SPEC §1D): equal-weight top-N by the momentum signal, no gate, no mask."""
    position = select_top_n(wide[signal].where(eligible), top_n)
    return weight_selected(position, "equal", [])


@dataclass
class RankResult:
    weights: pd.DataFrame  # signal_date x ticker, sums to 1 where anything is held
    positions: pd.DataFrame  # signal_date x ticker: 1..k position within the held set by z
    held_rank: pd.Series  # signal_date -> mean cross-sectional rank of the held names


def cross_sectional_order(score: pd.DataFrame) -> pd.DataFrame:
    """Rank 1 = best among eligible names (NaN where ineligible); ties by column order."""
    return score.rank(axis=1, ascending=False, method="first")


def select_with_hysteresis(
    score: pd.DataFrame, signal_dates: pd.DatetimeIndex, top_n: int, exit_rank: int
) -> pd.DataFrame:
    """Position within the held set (1..k by z) per signal date, NaN where not held."""
    order = cross_sectional_order(score.loc[signal_dates])
    tickers = list(order.columns)
    out = np.full(order.shape, np.nan)
    held: list[str] = []
    for i, (_, row) in enumerate(order.iterrows()):
        r = row.to_dict()
        kept = [t for t in held if np.isfinite(r[t]) and r[t] <= exit_rank]
        candidates = sorted(
            (t for t in tickers if t not in kept and np.isfinite(r[t]) and r[t] <= top_n),
            key=lambda t: r[t],
        )
        held = kept + candidates[: max(top_n - len(kept), 0)]
        for pos, t in enumerate(sorted(held, key=lambda t: r[t]), start=1):
            out[i, tickers.index(t)] = pos
    return pd.DataFrame(out, index=order.index, columns=tickers)


def average_held_rank(score: pd.DataFrame, positions: pd.DataFrame) -> pd.Series:
    """Mean cross-sectional rank of the held names per signal date (NaN when nothing is held)."""
    order = cross_sectional_order(score.loc[positions.index])
    return order.where(positions.notna()).mean(axis=1).rename("held_rank")


def rank_on_signal_dates(
    wide: dict[str, pd.DataFrame],
    eligible: pd.DataFrame,
    cfg: RankerConfig,
    signal_dates: pd.DatetimeIndex,
) -> RankResult:
    """``rank`` restricted to signal dates, stateful when ``exit_rank`` is set, with diagnostics."""
    signal_dates = signal_dates[signal_dates.isin(eligible.index)]
    if cfg.method != "momentum_zscore":
        weights = rank(wide, eligible, cfg).loc[signal_dates]
        positions = weights.where(weights > 0).rank(axis=1, ascending=False, method="first")
        held = pd.Series(np.nan, index=signal_dates, name="held_rank")
        return RankResult(weights=weights, positions=positions, held_rank=held)
    score = zscore_rows(wide[cfg.momentum_signal], eligible)
    if cfg.exit_rank is None:
        positions = select_top_n(score, cfg.top_n).loc[signal_dates]
    else:
        positions = select_with_hysteresis(score, signal_dates, cfg.top_n, cfg.exit_rank)
    vol = wide.get(VOL)
    weights = weight_selected(
        positions,
        cfg.weighting,
        cfg.conviction_tiers,
        vol.loc[signal_dates] if vol is not None else None,
        score.loc[signal_dates],
        cfg.softmax_temperature,
    )
    return RankResult(
        weights=weights, positions=positions, held_rank=average_held_rank(score, positions)
    )
