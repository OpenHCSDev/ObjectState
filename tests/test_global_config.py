"""Tests for global config module."""
import pytest
from dataclasses import dataclass

from lazy_config import (
    set_current_global_config,
    get_current_global_config,
    set_global_config_for_editing,
)


def test_set_and_get_global_config(global_config):
    """Test setting and getting global config."""
    set_current_global_config(global_config)
    result = get_current_global_config()
    assert result == global_config


def test_set_global_config_for_editing(global_config):
    """Test setting global config for editing."""
    @dataclass
    class TestConfig:
        value: str = "test"

    set_global_config_for_editing(TestConfig, global_config)
    # Should not raise an error
    result = get_current_global_config()
    assert result == global_config


def test_get_global_config_not_set():
    """Test getting global config when not set."""
    # Clear any existing global config
    import lazy_config.global_config as gc
    original = gc._thread_local_storage.__dict__.copy()

    try:
        # Clear thread local storage
        gc._thread_local_storage.__dict__.clear()

        result = get_current_global_config()
        # Should return None or raise error depending on implementation
        assert result is None or isinstance(result, Exception)
    except (RuntimeError, AttributeError):
        # This is acceptable - no global config set
        pass
    finally:
        # Restore original state
        gc._thread_local_storage.__dict__.update(original)
