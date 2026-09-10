"""Shared fixtures. Everything here is synthetic and offline — no network access."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_config_path() -> Path:
    return PROJECT_ROOT / "configs" / "base.yaml"


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    """A small, deterministic OHLCV frame shaped like a real yfinance download."""
    dates = pd.bdate_range("2020-01-01", periods=20, name="date")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1, len(dates)))
    df = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Adj Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, len(dates)),
        },
        index=dates,
    )
    return df
