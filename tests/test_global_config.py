"""Tests for global config module."""
import pytest
from dataclasses import dataclass

from objectstate import (
    set_current_global_config,
    get_current_global_config,
    set_global_config_for_editing,
    set_saved_global_config,
    set_live_global_config,
    get_saved_global_config,
    get_live_global_config,
    get_base_config_type,
)


def test_set_and_get_global_config(global_config):
    """Test setting and getting global config."""
    config_type = type(global_config)
    # Current API: set_current_global_config(config_type, config_instance)
    set_current_global_config(config_type, global_config)
    result = get_current_global_config(config_type)
    assert result == global_config


def test_set_global_config_for_editing(global_config):
    """Test setting global config for editing."""
    config_type = type(global_config)
    set_global_config_for_editing(config_type, global_config)
    # Should set both saved and live
    assert get_saved_global_config(config_type) == global_config
    assert get_live_global_config(config_type) == global_config


def test_get_global_config_not_set():
    """Test getting global config when not set for a specific type."""
    @dataclass
    class UnregisteredConfig:
        value: str = "test"

    # Getting config for unregistered type should return None
    result = get_current_global_config(UnregisteredConfig)
    assert result is None


def test_dual_config_pattern(global_config):
    """Test the dual saved/live config pattern."""
    config_type = type(global_config)

    # Create two different configs
    @dataclass
    class DualTestConfig:
        output_dir: str = "/tmp"
        num_workers: int = 4

    saved_config = DualTestConfig(output_dir="/saved", num_workers=4)
    live_config = DualTestConfig(output_dir="/live", num_workers=8)

    set_saved_global_config(DualTestConfig, saved_config)
    set_live_global_config(DualTestConfig, live_config)

    # get_current_global_config with use_live=True (default) returns live
    assert get_current_global_config(DualTestConfig, use_live=True) == live_config
    # get_current_global_config with use_live=False returns saved
    assert get_current_global_config(DualTestConfig, use_live=False) == saved_config
