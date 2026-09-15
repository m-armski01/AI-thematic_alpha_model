"""Rank-buffer hysteresis (brief v2, decision 2): entry at <= top_n, exit below exit_rank."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.golden import assert_golden
from tests.synthetic import make_config
from thematic_alpha.strategy import ranker

COLS = list("ABCDEFGHIJ")
TOP, EXIT = 5, 8


def _score(rows: list[list[float]]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-05", periods=len(rows), freq="W-FRI")
    return pd.DataFrame(rows, index=idx, columns=COLS, dtype=float)


def _by_rank(order: list[str]) -> list[float]:
    """Scores such that ``order[0]`` ranks 1, ``order[1]`` ranks 2, ..."""
    return [float(len(order) - order.index(c)) if c in order else -100.0 for c in COLS]


def _held(positions: pd.DataFrame, i: int) -> set[str]:
    return set(positions.columns[positions.iloc[i].notna()])


def test_entry_exit_asymmetry():
    day1 = _by_rank(list("ABCDEFGHIJ"))  # hold A..E
    day2 = _by_rank(list("ABCDFGEHIJ"))  # E slips to rank 7, F (not held) is rank 5... but no slot
    day3 = _by_rank(list("ABCDFGHIEJ"))  # E falls to rank 9 -> exits; F (rank 5) fills the slot
    pos = ranker.select_with_hysteresis(
        _score([day1, day2, day3]), _score([day1] * 3).index, TOP, EXIT
    )
    assert _held(pos, 0) == set("ABCDE")
    assert _held(pos, 1) == set("ABCDE")  # E stays at rank 7; F does not enter (no vacancy)
    assert _held(pos, 2) == set("ABCDF")  # rank 9 exits, the best non-held name at <= 5 enters


def test_unheld_name_at_buffer_rank_never_enters():
    day1 = _by_rank(list("ABCDEFGHIJ"))
    day2 = _by_rank(list("ABCDJEFGHI"))  # J jumps to rank 5 but all slots are taken
    day3 = _by_rank(list("ABCDJEFGHI"))
    idx = _score([day1] * 3).index
    pos = ranker.select_with_hysteresis(_score([day1, day2, day3]), idx, TOP, EXIT)
    assert _held(pos, 1) == set("ABCDE") and _held(pos, 2) == set("ABCDE")
    # ...and a name at rank 6-8 that is not held never enters even with a vacancy elsewhere.
    day4 = _by_rank(list("ABCDJFGHIE"))  # E at rank 10 exits; J (rank 5) enters, F (6) does not
    pos = ranker.select_with_hysteresis(
        _score([day1, day2, day3, day4]), _score([day1] * 4).index, TOP, EXIT
    )
    assert _held(pos, 3) == set("ABCDJ")


def test_newcomer_waits_while_incumbents_are_within_the_buffer():
    day1 = _by_rank(list("ABCDEFGHIJ"))
    day2 = _by_rank(list("JABCDEFGHI"))  # J is now rank 1, incumbents at ranks 2..6 (all <= 8)
    pos = ranker.select_with_hysteresis(_score([day1, day2]), _score([day1] * 2).index, TOP, EXIT)
    assert _held(pos, 1) == set("ABCDE")
    held_rank = ranker.average_held_rank(_score([day1, day2]), pos)
    assert held_rank.tolist() == pytest.approx([3.0, 4.0])  # (1..5)/5 then (2..6)/5


def test_ineligible_incumbent_exits():
    day1 = _by_rank(list("ABCDEFGHIJ"))
    day2 = _by_rank(list("ABCDEFGHIJ"))
    score = _score([day1, day2])
    score.iloc[1, COLS.index("C")] = np.nan  # C becomes ineligible on day 2
    pos = ranker.select_with_hysteresis(score, score.index, TOP, EXIT)
    assert _held(pos, 1) == set("ABDEF")  # C out, F (rank 5 among the eligible) in


def test_held_count_never_exceeds_top_n():
    rng = np.random.default_rng(0)
    score = _score(rng.normal(size=(120, len(COLS))).tolist())
    score[score.abs() < 0.05] = np.nan  # some ineligible names
    pos = ranker.select_with_hysteresis(score, score.index, TOP, EXIT)
    counts = pos.notna().sum(axis=1)
    assert counts.max() <= TOP and counts.min() >= 1
    # positions within the held set are 1..k by score
    for i in range(len(pos)):
        row = pos.iloc[i].dropna().sort_values()
        assert row.tolist() == list(range(1, len(row) + 1))
        assert score.iloc[i][row.index].is_monotonic_decreasing


def test_average_held_rank_is_three_for_plain_top_five():
    rng = np.random.default_rng(1)
    score = _score(rng.normal(size=(60, len(COLS))).tolist())
    pos = ranker.select_with_hysteresis(score, score.index, TOP, TOP)
    assert ranker.average_held_rank(score, pos).tolist() == pytest.approx([3.0] * 60)


def test_rank_on_signal_dates_matches_stateless_when_exit_rank_is_top_n():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2024-01-01", periods=200)
    wide = {
        "mom_63": pd.DataFrame(rng.normal(size=(200, 10)), index=idx, columns=COLS),
        "vol_21": pd.DataFrame(0.2, index=idx, columns=COLS),
    }
    elig = pd.DataFrame(True, index=idx, columns=COLS)
    signal = idx[::5]
    cfg = make_config(ranker={"weighting": "equal", "exit_rank": None}).ranker
    stateless = ranker.rank(wide, elig, cfg).loc[signal]
    looped = ranker.rank_on_signal_dates(
        wide, elig, cfg.model_copy(update={"exit_rank": TOP}), signal
    )
    pd.testing.assert_frame_equal(stateless, looped.weights)
    assert looped.held_rank.tolist() == pytest.approx([3.0] * len(signal))


def test_config_rejects_exit_rank_below_top_n():
    with pytest.raises(ValueError):
        make_config(ranker={"exit_rank": 4})


def test_exit_rank_equal_to_top_n_is_golden():
    assert_golden(ranker={"exit_rank": 5})
