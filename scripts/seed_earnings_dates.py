"""Pre-fill data/reference/earnings_dates.csv from yfinance for manual review.

    python scripts/seed_earnings_dates.py [--universe data/reference/universe.csv]
                                          [--out data/reference/earnings_dates.csv] [--limit 100]

yfinance earnings dates are unreliable (SPEC §5.4): review the output against each company's
investor-relations calendar before committing it. Existing rows in the CSV are kept and merged;
the file is written sorted and de-duplicated with its comment header preserved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from thematic_alpha.strategy.event_mask import load_earnings_dates  # noqa: E402

HEADER = """ticker,earnings_date
# Maintain this file by hand. One row per earnings release. Dates are ISO YYYY-MM-DD.
# The event mask (Layer 1C) reads this file; any ticker with no rows here "fails open"
# (no mask applied) and logs a warning.
# Seeded from yfinance by scripts/seed_earnings_dates.py and then reviewed manually.
"""

SPOT_CHECK = ["NVDA", "MSFT", "AMZN"]


def fetch(ticker: str, limit: int) -> pd.DatetimeIndex:
    import yfinance as yf

    df = yf.Ticker(ticker).get_earnings_dates(limit=limit)
    if df is None or df.empty:
        return pd.DatetimeIndex([])
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    return pd.DatetimeIndex(sorted(set(idx.normalize())))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=ROOT / "data/reference/universe.csv", type=Path)
    ap.add_argument("--out", default=ROOT / "data/reference/earnings_dates.csv", type=Path)
    ap.add_argument(
        "--limit", default=100, type=int, help="max dates per ticker (Yahoo caps this at 100)"
    )
    args = ap.parse_args()

    tickers = pd.read_csv(args.universe, comment="#")["ticker"].astype(str).tolist()
    existing = load_earnings_dates(args.out) if args.out.exists() else {}
    merged: dict[str, set[pd.Timestamp]] = {t: set(d) for t, d in existing.items()}

    for t in tickers:
        try:
            dates = fetch(t, args.limit)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{t}: FAILED ({exc})")
            continue
        before = len(merged.get(t, set()))
        merged.setdefault(t, set()).update(dates)
        got = merged[t]
        span = f"{min(got).date()} -> {max(got).date()}" if got else "none"
        print(f"{t}: {len(dates)} from yfinance, {len(got)} total (+{len(got) - before}) | {span}")

    rows = sorted((t, d) for t, ds in merged.items() for d in ds)
    with open(args.out, "w") as fh:
        fh.write(HEADER)
        for t, d in rows:
            fh.write(f"{t},{d.strftime('%Y-%m-%d')}\n")
    print(f"\nwrote {len(rows)} rows -> {args.out}")

    print("\nSpot-check list (compare with investor-relations calendars):")
    for t in SPOT_CHECK:
        last = sorted(merged.get(t, set()))[-8:]
        print(f"  {t}: {', '.join(d.strftime('%Y-%m-%d') for d in last)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
