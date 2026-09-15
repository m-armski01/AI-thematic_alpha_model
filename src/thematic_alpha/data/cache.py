"""Parquet cache helpers shared by the price and macro loaders.

A cached frame lives at ``{cache_dir}/{kind}/{key}.parquet`` and is considered fresh when its
mtime is within ``max_cache_age_days``. Nothing here touches the network.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd


def cache_path(cache_dir: str | Path, kind: str, key: str) -> Path:
    return Path(cache_dir) / kind / f"{key}.parquet"


def is_cache_fresh(path: Path, max_cache_age_days: int) -> bool:
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_cache_age_days * 86400


def read_cache(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df


def write_cache(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
