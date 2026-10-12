"""The stored global config: what holds it while no state does."""
from dataclasses import dataclass

import pytest

from objectstate import get_live_global_config, get_saved_global_config, set_global_config


def test_a_stored_global_config_is_both_the_live_and_the_saved_one(global_config):
    config_type = type(global_config)
    set_global_config(config_type, global_config)
    assert get_saved_global_config(config_type) is global_config
    assert get_live_global_config(config_type) is global_config


def test_no_global_config_reads_as_none():
    @dataclass
    class NeverSet:
        value: str = "test"

    assert get_live_global_config(NeverSet) is None
    assert get_saved_global_config(NeverSet) is None


def test_a_global_config_must_be_an_instance_of_its_type() -> None:
    @dataclass
    class ExpectedConfig:
        value: str = "expected"

    @dataclass
    class OtherConfig:
        value: str = "other"

    with pytest.raises(TypeError, match="ExpectedConfig"):
        set_global_config(ExpectedConfig, OtherConfig())
    with pytest.raises(TypeError, match="key must be a type"):
        set_global_config("ExpectedConfig", ExpectedConfig())
