"""Freeze the golden regression fixture (tests/fixtures/golden_*).

Runs the pipeline on the wide synthetic market with Layer 1 settings and writes the target
weights, the trade log and the turnover series. ``tests/test_golden.py`` asserts that all-neutral
settings reproduce these files exactly, so this script is run once, when the fixture is created,
and never as part of a normal build. Re-freezing requires a deliberate decision: it redefines
what "Layer 1 behaviour" means.

    python scripts/freeze_golden.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import synthetic  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> int:
    FIXTURES.mkdir(exist_ok=True)
    market = synthetic.make_wide_market()
    synthetic.write_earnings_csv(market.earnings, FIXTURES / "golden_earnings.csv")
    config = synthetic.wide_config()
    _, features, strategy, results = synthetic.run_pipeline(market, config, FIXTURES)
    strat = results["strategy"]
    strategy.target_weights.to_csv(FIXTURES / "golden_targets.csv", float_format="%.17g")
    strat.trades.to_csv(FIXTURES / "golden_trades.csv", index=False, float_format="%.17g")
    strat.turnover_series.rename("turnover").to_csv(
        FIXTURES / "golden_turnover.csv", float_format="%.17g"
    )
    c = strategy.composed
    meta = {
        "n_signal_dates": int(len(strategy.signal_dates)),
        "n_gated_signal_dates": int((c.exposure < 1).sum()),
        "entries_blocked": int(c.entries_blocked),
        "n_trades": int(len(strat.trades)),
        "final_equity": {n: float(results[n].final_equity) for n in results},
        "first_eligible": {
            t: str(features.eligible.index[features.eligible[t].to_numpy().argmax()].date())
            for t in features.eligible.columns
        },
    }
    (FIXTURES / "golden_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
