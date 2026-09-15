"""Gate evaluation cadence (brief v2, decision 4c): monthly sampling, held between evaluations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.golden import assert_golden, golden_run
from tests.synthetic import make_config
from thematic_alpha.backtest.attribution import gate_diagnostics
from thematic_alpha.backtest.schedule import signal_dates
from thematic_alpha.strategy.macro_gate import applied_gate, evaluation_dates

SESSIONS = pd.bdate_range("2023-01-02", periods=520)
WEEKLY = signal_dates(SESSIONS, "weekly", "friday")


def _gate_daily(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    risk_off = pd.Series(rng.random(len(SESSIONS)) < 0.4, index=SESSIONS)
    exposure = pd.Series(np.where(risk_off, 0.5, 1.0), index=SESSIONS)
    return pd.DataFrame({"exposure": exposure, "risk_off": risk_off})


@pytest.mark.parametrize("action", ["scale", "block_increases"])
def test_state_is_constant_between_evaluation_dates_and_taken_from_the_latest_one(action):
    cfg = make_config().macro_gate.model_copy(update={"evaluation": "monthly", "action": action})
    daily = _gate_daily()
    state = applied_gate(daily, WEEKLY, cfg)
    evals = evaluation_dates(WEEKLY, "monthly")
    assert evals[0] == WEEKLY[0] and state.evaluated.sum() == len(evals)
    # Monthly evaluation dates are the last weekly signal date of each calendar month.
    monthly = signal_dates(SESSIONS, "monthly", "friday")
    assert set(evals) == set(monthly) | {WEEKLY[0]}
    s = state.state
    for d in WEEKLY:
        latest = evals[evals <= d][-1]
        assert s.loc[d] == s.loc[latest]  # constant between evaluations...
        expected = daily.loc[latest, "exposure" if action == "scale" else "risk_off"]
        assert s.loc[d] == expected  # ...and equal to the daily gate on the latest evaluation
    changes = s.index[1:][s.to_numpy()[1:] != s.to_numpy()[:-1]]
    assert set(changes) <= set(evals[1:])  # changes only on evaluation dates
    assert gate_diagnostics(s, 2.0).n_transitions <= len(evals)


def test_weekly_evaluation_samples_every_signal_date():
    cfg = make_config().macro_gate.model_copy(update={"evaluation": "weekly", "action": "scale"})
    daily = _gate_daily()
    state = applied_gate(daily, WEEKLY, cfg)
    assert state.evaluated.all()
    pd.testing.assert_series_equal(
        state.exposure, daily["exposure"].reindex(WEEKLY), check_names=False
    )


def test_monthly_cadence_reduces_transitions_on_the_golden_market():
    _, _, weekly, _ = golden_run(macro_gate={"evaluation": "weekly"})
    _, _, monthly, _ = golden_run(macro_gate={"evaluation": "monthly"})
    tw, tm = (gate_diagnostics(s.applied.state, 1.0).n_transitions for s in (weekly, monthly))
    assert tm <= tw and tm <= int(monthly.applied.evaluated.sum())


def test_weekly_evaluation_is_golden():
    assert_golden(macro_gate={"evaluation": "weekly"})
