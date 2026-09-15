"""Universe definition & metadata (SPEC §5.1, §5.4).

Reads ``data/reference/universe.csv`` and exposes ticker -> exchange / currency maps plus the
optional ``regime_start_date`` truncation (IREN's mining -> datacenter pivot, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ["ticker", "name", "segment", "exchange", "currency"]
OPTIONAL_COLUMNS = ["regime_start_date", "notes"]


@dataclass
class Universe:
    frame: pd.DataFrame

    @property
    def tickers(self) -> list[str]:
        return self.frame["ticker"].tolist()

    @property
    def exchange_of(self) -> dict[str, str]:
        return dict(zip(self.frame["ticker"], self.frame["exchange"], strict=True))

    @property
    def currency_of(self) -> dict[str, str]:
        return dict(zip(self.frame["ticker"], self.frame["currency"], strict=True))

    @property
    def regime_start(self) -> dict[str, pd.Timestamp]:
        """Tickers with a non-null regime_start_date -> that date."""
        col = self.frame["regime_start_date"]
        return {t: d for t, d in zip(self.frame["ticker"], col, strict=True) if pd.notna(d)}


def load_universe(path: str | Path) -> Universe:
    df = pd.read_csv(path, comment="#", dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"universe file {path} is missing required columns: {missing}")
    for c in OPTIONAL_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["ticker"] = df["ticker"].str.strip()
    if df["ticker"].duplicated().any():
        dupes = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
        raise ValueError(f"universe file {path} has duplicate tickers: {dupes}")
    df["regime_start_date"] = pd.to_datetime(df["regime_start_date"], errors="raise")
    return Universe(df.reset_index(drop=True))


def apply_regime_start(
    frames: dict[str, pd.DataFrame], universe: Universe
) -> dict[str, pd.DataFrame]:
    """Drop history before each ticker's regime_start_date (no-op for tickers without one)."""
    out = dict(frames)
    for ticker, start in universe.regime_start.items():
        if ticker in out:
            out[ticker] = out[ticker].loc[out[ticker].index >= start]
    return out
