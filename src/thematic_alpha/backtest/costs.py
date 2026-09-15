"""Transaction costs on traded notional (SPEC §1D).

* ``bps``      : traded_notional x (bps_per_side + slippage_bps) / 1e4
* ``flat_fee`` : traded_notional x slippage_bps / 1e4 + flat_fee x positions changed
                 (slippage is a market cost, not a broker fee, so it stays on)
* ``both``     : traded_notional x (bps_per_side + slippage_bps) / 1e4 + flat_fee x changed
"""

from __future__ import annotations

from thematic_alpha.config import CostsConfig


def cost_rate(cfg: CostsConfig) -> float:
    """Proportional cost per unit of traded notional."""
    bps = cfg.slippage_bps + (cfg.bps_per_side if cfg.model in ("bps", "both") else 0.0)
    return bps / 1e4


def flat_fee(n_changed: int, cfg: CostsConfig) -> float:
    """Fixed fee component for ``n_changed`` positions touched (0 under the pure bps model)."""
    return cfg.flat_fee * n_changed if cfg.model in ("flat_fee", "both") else 0.0


def transaction_cost(traded_notional: float, n_changed: int, cfg: CostsConfig) -> float:
    return float(traded_notional * cost_rate(cfg) + flat_fee(n_changed, cfg))
