"""Position limits (SPEC §1C): ``max_position_weight`` and ``cash_floor``.

Weight above the per-name cap goes to cash rather than being redistributed. The house-money
rule (trim to recover principal + trailing stop) is a Layer 2 component; when enabled in config
it is announced once and otherwise ignored here.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from thematic_alpha.config import SizingConfig

logger = logging.getLogger("thematic_alpha.strategy.sizing")


def apply_limits(
    weights: pd.DataFrame, max_position_weight: float, cash_floor: float
) -> pd.DataFrame:
    capped = weights.clip(lower=0.0, upper=max_position_weight)
    budget = 1.0 - cash_floor
    total = capped.sum(axis=1)
    scale = np.where(total > budget, budget / total.replace(0.0, np.nan), 1.0)
    return capped.mul(pd.Series(scale, index=capped.index).fillna(1.0), axis=0)


def announce_house_money(cfg: SizingConfig) -> None:
    if cfg.house_money.enabled:
        logger.warning(
            "sizing.house_money.enabled=true but the house-money rule is a Layer 2 component; "
            "it is not applied in Layer 1."
        )
