"""Tests for context manager module."""

from hieraconf import (
    clear_current_temp_global,
    config_context,
    extract_all_configs,
    get_current_temp_global,
    merge_configs,
    set_base_config_type,
    set_current_temp_global,
)
from tests.conftest import TestGlobalConfig


def test_config_context_basic(global_config):
    """Test basic config_context usage."""
    set_base_config_type(TestGlobalConfig)
    with config_context(global_config):
        current = get_current_temp_global()
        assert current is not None
        assert current.output_dir == "/data"
        assert current.num_workers == 8


def test_config_context_nested(global_config, pipeline_config):
    """Test nested config_context."""
    set_base_config_type(TestGlobalConfig)
    with config_context(global_config):
        outer = get_current_temp_global()
        assert outer.output_dir == "/data"

        with config_context(pipeline_config):
            inner = get_current_temp_global()
            # Should have both configs merged
            assert hasattr(inner, "output_dir")  # from global
            assert hasattr(inner, "batch_size")  # from pipeline


def test_config_context_cleanup(global_config):
    """Test that config_context cleans up after exiting."""
    set_base_config_type(TestGlobalConfig)
    with config_context(global_config):
        assert get_current_temp_global() is not None

    # After exiting, context should be cleared
    try:
        result = get_current_temp_global()
        # If no exception, should be None or raise LookupError
        assert result is None
    except LookupError:
        # This is also acceptable
        pass


def test_set_and_clear_current_temp_global(global_config):
    """Test manually setting and clearing temp global."""
    set_current_temp_global(global_config)
    assert get_current_temp_global() == global_config

    clear_current_temp_global()
    try:
        result = get_current_temp_global()
        assert result is None
    except LookupError:
        pass


def test_merge_configs(global_config, pipeline_config):
    """Test merging multiple configs."""
    # merge_configs now takes (base, overrides_dict)
    overrides = {"batch_size": 64, "learning_rate": 0.01}
    merged = merge_configs(global_config, overrides)
    assert hasattr(merged, "output_dir")  # from global
    assert hasattr(merged, "batch_size")  # from overrides
    assert merged.batch_size == 64


def test_extract_all_configs(global_config):
    """Test extracting all configs from a merged config."""
    set_base_config_type(TestGlobalConfig)
    with config_context(global_config):
        current = get_current_temp_global()
        configs = extract_all_configs(current)
        assert isinstance(configs, dict)
        # Should contain the global config by type name
        assert len(configs) > 0
