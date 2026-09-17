"""Typed, validated configuration models for the full strategy config schema (SPEC §6).

Every tunable in the strategy lives in a YAML config and is validated here by pydantic v2.
`extra="forbid"` on every model means a typo'd or unknown key raises a clear error instead of
being silently ignored. Load with ``Config.from_yaml("configs/base.yaml")``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Base(BaseModel):
    """Base with strict schema: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class RunConfig(_Base):
    name: str = "base"
    seed: int = 42
    start_date: str = "2015-01-01"
    end_date: str | None = None  # null = today
    base_currency: Literal["EUR", "USD"] = "EUR"


class DataConfig(_Base):
    max_cache_age_days: int = Field(ge=0)
    min_history_days: int = Field(gt=0)
    # Download start (SPEC §5.2). run.start_date is the *backtest* start; features need warm-up.
    history_start: str = "1998-01-01"
    # |1-day return| above this is flagged in outputs/data_quality.md for manual review.
    suspicious_return_threshold: float = Field(default=0.25, gt=0.0)
    # FRED values keyed by observation date are typically published the next day. Shift macro
    # series by this many sessions before any feature/gate sees them (conservative, no lookahead).
    macro_publication_lag_days: int = Field(default=1, ge=0)
    # Liquidity screen (base currency): a name is eligible only once its 21-day average daily
    # traded value is at least this. 0.0 = off (Layer 1); applied only when > 0.
    min_dollar_volume_21d: float = Field(default=0.0, ge=0.0)


class UniverseConfig(_Base):
    file: str
    benchmarks: list[str]
    # Report framing only: "hindsight" prints the hindsight-bias paragraph; "point_in_time"
    # states how the universe was defined and the residual ETF-delisting bias.
    selection: Literal["hindsight", "point_in_time"] = "hindsight"


class FeaturesConfig(_Base):
    momentum_windows: list[int]
    vol_windows: list[int]
    ma_windows: list[int]
    skip_recent_days: int = Field(ge=0)


class MacroGateConfig(_Base):
    enabled: bool = True
    vix_threshold: float
    vix_scale_factor: float = Field(ge=0.0, le=1.0)
    yield_change_window: int = Field(gt=0)
    yield_change_threshold: float
    yield_scale_factor: float = Field(ge=0.0, le=1.0)
    oil_change_window: int = Field(gt=0)
    oil_change_threshold: float
    oil_scale_factor: float = Field(ge=0.0, le=1.0)
    min_exposure: float = Field(ge=0.0, le=1.0)
    combination: Literal["multiplicative", "min", "average"] = "multiplicative"
    # (a) What the gate does. "scale" multiplies the book by the exposure (Layer 1).
    # "block_increases": any engaged sub-gate is a boolean risk-off state; non-exempt names are
    # capped at their previous target (no increases, no new entries), blocked weight stays in
    # cash, and the scale factors / min_exposure are unused.
    action: Literal["scale", "block_increases"] = "scale"
    # Universe ``segment`` values that trade freely while risk-off (e.g. ["defensive"]).
    block_exempt_segments: list[str] = Field(default_factory=list)
    # (b) Schmitt trigger per sub-gate: engage when the signal is above the engage threshold,
    # release only when it is at or below the release threshold, hold the state in between.
    # None -> release = engage, which is exactly the Layer 1 comparator.
    vix_release_threshold: float | None = None
    yield_release_threshold: float | None = None
    oil_release_threshold: float | None = None
    # (c) Evaluation cadence. "weekly": the gate is sampled on every signal date (Layer 1).
    # "monthly": sampled on the last weekly signal date of each month (plus the first signal
    # date) and held constant on the weekly signal dates in between; ranking stays weekly.
    evaluation: Literal["weekly", "monthly"] = "weekly"

    @model_validator(mode="after")
    def _release_not_above_engage(self) -> MacroGateConfig:
        for name, engage, release in (
            ("vix", self.vix_threshold, self.vix_release_threshold),
            ("yield", self.yield_change_threshold, self.yield_release_threshold),
            ("oil", self.oil_change_threshold, self.oil_release_threshold),
        ):
            if release is not None and release > engage:
                raise ValueError(
                    f"{name}_release_threshold={release} must not exceed the engage "
                    f"threshold {engage}"
                )
        return self

    def release_threshold(self, name: str) -> float:
        engage = {
            "vix": self.vix_threshold,
            "yield": self.yield_change_threshold,
            "oil": self.oil_change_threshold,
        }[name]
        release = {
            "vix": self.vix_release_threshold,
            "yield": self.yield_release_threshold,
            "oil": self.oil_release_threshold,
        }[name]
        return engage if release is None else release


class RankerConfig(_Base):
    method: Literal["momentum_zscore", "equal_weight"] = "momentum_zscore"
    top_n: int = Field(gt=0)
    weighting: Literal["equal", "inverse_vol", "conviction_tier", "softmax"] = "conviction_tier"
    conviction_tiers: list[float]
    # softmax over the held names' momentum z-scores: w_i ∝ exp((z_i - max z) / τ). Neutral
    # default 1.0 is unused unless weighting == "softmax".
    softmax_temperature: float = Field(default=1.0, gt=0.0)
    # Hysteresis (fixed slots): a held name stays while its rank is <= exit_rank; a name enters
    # only at rank <= top_n and only into a vacant slot. None -> top_n, which is plain top-N.
    exit_rank: int | None = None

    @model_validator(mode="after")
    def _tiers_cover_top_n(self) -> RankerConfig:
        if self.weighting == "conviction_tier" and len(self.conviction_tiers) < self.top_n:
            raise ValueError(
                f"conviction_tiers has {len(self.conviction_tiers)} entries "
                f"but top_n={self.top_n}; need at least top_n tiers."
            )
        if self.exit_rank is not None and self.exit_rank < self.top_n:
            raise ValueError(f"exit_rank={self.exit_rank} must be >= top_n={self.top_n}")
        return self

    @property
    def effective_exit_rank(self) -> int:
        return self.top_n if self.exit_rank is None else self.exit_rank


class EventMaskConfig(_Base):
    enabled: bool = True
    file: str = "data/reference/earnings_dates.csv"
    block_days_before_earnings: int = Field(ge=0)
    block_new_entries_only: bool = True


class SizingConfig(_Base):
    max_position_weight: float = Field(gt=0.0, le=1.0)
    cash_floor: float = Field(ge=0.0, le=1.0)


class TurnoverConfig(_Base):
    """Turnover controls applied in the engine, to strategy runs only (benchmarks never)."""

    # Held->held trades whose |target - drifted weight| is below this are skipped; the residual
    # stays in cash. Full exits and new entries always trade. 0.0 = off (Layer 1).
    position_band: float = Field(default=0.0, ge=0.0, lt=1.0)


class BacktestConfig(_Base):
    rebalance: Literal["weekly", "monthly"] = "weekly"
    rebalance_day: Literal["monday", "tuesday", "wednesday", "thursday", "friday"] = "friday"
    execution_lag_days: int = Field(ge=0)
    execution_price: Literal["open", "close"] = "open"
    initial_capital: float = Field(gt=0.0)
    # Idle cash accrues the risk-free rate (``risk.rf_series``, calendar-day basis) for the
    # strategy and every benchmark alike. False = cash earns 0 (Layer 1).
    cash_earns_rf: bool = False


class CostsConfig(_Base):
    model: Literal["bps", "flat_fee", "both"] = "bps"
    bps_per_side: float = Field(ge=0.0)
    flat_fee: float = Field(ge=0.0)
    slippage_bps: float = Field(ge=0.0)


class RiskConfig(_Base):
    rf_series: str = "DTB3"
    var_confidence: list[float]
    rolling_beta_window: int = Field(gt=0)

    @field_validator("var_confidence")
    @classmethod
    def _confidences_in_unit_interval(cls, v: list[float]) -> list[float]:
        for c in v:
            if not 0.0 < c < 1.0:
                raise ValueError(f"var_confidence entries must be in (0, 1); got {c}")
        return v


class Config(_Base):
    """Top-level config mirroring the full YAML schema."""

    run: RunConfig
    data: DataConfig
    universe: UniverseConfig
    features: FeaturesConfig
    macro_gate: MacroGateConfig
    ranker: RankerConfig
    event_mask: EventMaskConfig
    sizing: SizingConfig
    turnover: TurnoverConfig = TurnoverConfig()
    backtest: BacktestConfig
    costs: CostsConfig
    risk: RiskConfig

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        """Load and validate a config from a YAML file."""
        path = Path(path)
        with path.open("r") as fh:
            raw = yaml.safe_load(fh)
        if raw is None:
            raise ValueError(f"Config file {path} is empty.")
        return cls.model_validate(raw)
