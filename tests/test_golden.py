"""Golden regression: all-neutral settings reproduce the frozen Layer 1 run exactly.

The fixture must exercise every Layer 1 mechanism, otherwise a regression in one of them could
hide behind a green test; ``test_fixture_exercises_gate_mask_and_listings`` checks that.
"""

from __future__ import annotations

from tests.golden import assert_golden, load_golden


def test_fixture_exercises_gate_mask_and_listings():
    _, _, _, meta = load_golden()
    assert meta["n_gated_signal_dates"] > 0
    assert meta["entries_blocked"] > 0
    first = meta["first_eligible"]
    assert first["W11"] > "2019-01-02" and first["W12"] > first["W11"]  # mid-window listings


def test_all_neutral_reproduces_layer1():
    assert_golden()
