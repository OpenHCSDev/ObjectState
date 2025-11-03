"""Tests for global config module."""

from dataclasses import dataclass

from hieraconf import (
    get_current_global_config,
    set_current_global_config,
    set_global_config_for_editing,
)


def test_set_and_get_global_config(global_config):
    """Test setting and getting global config."""
    from tests.conftest import TestGlobalConfig

    set_current_global_config(TestGlobalConfig, global_config)
    result = get_current_global_config(TestGlobalConfig)
    assert result == global_config


def test_set_global_config_for_editing(global_config):
    """Test setting global config for editing."""

    @dataclass
    class TestConfig:
        value: str = "test"

    test_config = TestConfig(value="custom")
    set_global_config_for_editing(TestConfig, test_config)
    # Should not raise an error
    result = get_current_global_config(TestConfig)
    assert result == test_config


def test_get_global_config_not_set():
    """Test getting global config when not set."""

    @dataclass
    class UnusedConfig:
        value: str = "test"

    # Get config for a type that was never set
    result = get_current_global_config(UnusedConfig)
    # Should return None when not set
    assert result is None
