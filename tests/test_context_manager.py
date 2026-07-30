"""Tests for context manager module."""
import pytest
from dataclasses import dataclass, field
from typing import Annotated

from objectstate import (
    LazyDataclassFactory,
    config_context,
    get_current_temp_global,
    set_current_temp_global,
    clear_current_temp_global,
    merge_configs,
    extract_all_configs,
)


def test_config_context_basic(global_config):
    """Test basic config_context usage."""
    with config_context(global_config):
        current = get_current_temp_global()
        assert current is not None
        assert current.output_dir == "/data"
        assert current.num_workers == 8


def test_config_context_nested(global_config, pipeline_config):
    """Test nested config_context."""
    with config_context(global_config):
        outer = get_current_temp_global()
        assert outer.output_dir == "/data"

        with config_context(pipeline_config):
            inner = get_current_temp_global()
            # Should have both configs merged - inner context merges pipeline values
            assert hasattr(inner, 'output_dir')  # from global
            assert hasattr(inner, 'batch_size')  # from pipeline


def test_config_context_cleanup(global_config):
    """Test that config_context cleans up after exiting."""
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


def test_merge_configs(global_config):
    """Test merging overrides into base config.

    Current API: merge_configs(base, overrides_dict)
    """
    overrides = {'output_dir': '/overridden', 'num_workers': 16}
    merged = merge_configs(global_config, overrides)

    assert merged.output_dir == '/overridden'
    assert merged.num_workers == 16
    # Unchanged values remain
    assert merged.debug == global_config.debug


def test_extract_all_configs(global_config):
    """Test extracting all configs from a merged config."""
    with config_context(global_config):
        current = get_current_temp_global()
        configs = extract_all_configs(current)
        assert isinstance(configs, dict)
        assert configs[type(current)] is current
        assert len(configs) > 0


def test_extract_all_configs_uses_resolved_nominal_field_types() -> None:
    @dataclass
    class ChildConfig:
        value: str = "child"

    @dataclass
    class ParentConfig:
        payload: Annotated[ChildConfig, "configuration"] = field(
            default_factory=ChildConfig
        )

    parent = ParentConfig()

    assert extract_all_configs(parent) == {
        ParentConfig: parent,
        ChildConfig: parent.payload,
    }


def test_extract_all_configs_rejects_ambiguous_same_type_fields() -> None:
    @dataclass
    class ChildConfig:
        value: str

    @dataclass
    class ParentConfig:
        first: ChildConfig
        second: ChildConfig

    with pytest.raises(ValueError, match="second ChildConfig instance"):
        extract_all_configs(
            ParentConfig(
                first=ChildConfig("first"),
                second=ChildConfig("second"),
            )
        )


def test_extract_all_configs_rejects_value_outside_declared_field_type() -> None:
    @dataclass
    class ChildConfig:
        value: str

    @dataclass
    class ParentConfig:
        payload: ChildConfig

    with pytest.raises(TypeError, match="declares ChildConfig"):
        extract_all_configs(ParentConfig(payload="not a config"))


def test_extract_all_configs_accepts_concrete_value_for_lazy_declared_owner() -> None:
    @dataclass
    class ChildConfig:
        value: str = "child"

    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class ParentConfig:
        payload: LazyChildConfig = field(default_factory=LazyChildConfig)

    concrete = ChildConfig(value="concrete")
    parent = ParentConfig(payload=concrete)

    assert extract_all_configs(parent) == {
        ParentConfig: parent,
        ChildConfig: concrete,
    }
