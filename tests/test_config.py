"""Config validation tests (SPEC Layer 0 deliverable #2: invalid config raises clearly)."""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from thematic_alpha.config import Config


def _load_raw(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def test_base_config_loads(base_config_path):
    cfg = Config.from_yaml(base_config_path)
    assert cfg.run.base_currency == "EUR"
    assert cfg.ranker.top_n == 5
    assert cfg.macro_gate.combination == "multiplicative"


def test_bad_enum_value_raises(base_config_path):
    raw = _load_raw(base_config_path)
    raw["macro_gate"]["combination"] = "bogus"
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_unknown_key_raises(base_config_path):
    raw = _load_raw(base_config_path)
    raw["run"]["totally_unknown_key"] = 123
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_out_of_range_value_raises(base_config_path):
    raw = _load_raw(base_config_path)
    raw["macro_gate"]["min_exposure"] = 5.0  # must be in [0, 1]
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_conviction_tiers_must_cover_top_n(base_config_path):
    raw = copy.deepcopy(_load_raw(base_config_path))
    raw["ranker"]["weighting"] = "conviction_tier"
    raw["ranker"]["top_n"] = 10  # more than the 5 conviction tiers provided
    with pytest.raises(ValidationError):
        Config.model_validate(raw)


def test_momentum_signal_must_be_a_computed_feature(base_config_path):
    import pytest as _pytest

    from thematic_alpha.config import Config

    cfg = Config.from_yaml(base_config_path)
    assert cfg.ranker.momentum_signal == "mom_63"
    raw = cfg.model_dump()
    raw["ranker"]["momentum_signal"] = "mom_500"
    with _pytest.raises(ValueError, match="momentum_signal"):
        Config.model_validate(raw)
    raw["ranker"]["momentum_signal"] = "mom_252"
    assert Config.model_validate(raw).ranker.momentum_signal == "mom_252"
