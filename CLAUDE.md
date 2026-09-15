# thematic-alpha

Spec: `../AI sector quantbot SPEC.md`. Status and results: `README.md` → "Build status". Layer 1 is
done (branch `1-build-layer-1`, GitHub issue #1); Layer 2 is next, house-money simulator first.

## Environment and commands

- Interpreter: `.venv/bin/python` (3.12) in this directory. This directory is the GitHub repo; the
  sibling `../thematic-alpha/` folder is a dead Layer-0 copy — ignore it.
- Run the pipeline: `python -m thematic_alpha.run --config configs/base.yaml` (`--refresh` forces
  re-download; `--layer 0` is the NVDA smoke test).
- Tests: `pytest` — fully offline, synthetic two-exchange market in `tests/synthetic.py`.
- Lint: `ruff check . && black --check .` (line length 100).

## Rules

- Keep the checkpoint rhythm: one sub-layer → lint, tests, real demo run, one commit.
- No lookahead: `tests/test_no_lookahead.py` must keep passing. Features at `t` use data through
  the close of `t`; macro series carry a one-session publication lag.
- Never back-fill or interpolate macro data; never impute prices (missing history = exclusion).
- Every performance figure is net of costs and reported next to the equal-weight buy-and-hold of
  the same basket. Hindsight bias stays the first thing the README and report say.

## Data quirks (already handled — don't re-investigate)

- FRED is read via the keyless `fredgraph.csv` endpoint; `pandas-datareader` is deliberately not used
  (its pin imports `distutils`, gone in 3.12).
- `exchange_calendars` must stay ≥ 4.13: older versions lack the 2025-01-09 NYSE closure and Korean
  ad-hoc holidays, which shows up as the same phantom gap on every ticker.
- SK Hynix (`000660.KS`): yfinance adjusted close is negative through 2002 → `regime_start_date =
  2003-01-02` in `universe.csv`. Zero-volume phantom bars on KRX holidays are dropped in
  `prices.drop_phantom_bars`. Two real gaps (2022-01-03, 2022-05-09) leave its target in cash
  that day — expected.
- yfinance `get_earnings_dates` caps `limit` at 100, and its forward dates can be off by a day.

## Earnings dates are hand-reviewed

`data/reference/earnings_dates.csv` is seeded by `scripts/seed_earnings_dates.py` and then checked
against investor-relations calendars by the user. Never regenerate and commit it without the user
reviewing the printed spot-check list, and confirm the pipeline logs a nonzero
"entries blocked pre-earnings" afterwards.

## Report determinism

`outputs/report.md` no longer embeds the git hash (it is logged to stdout at the start of a run), so
a rerun on the same data is byte-identical and the committed report never lags a commit.
