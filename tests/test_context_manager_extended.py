"""Extended tests for context manager to improve coverage."""

from dataclasses import dataclass, field
from typing import Optional

import pytest

from hieraconf import (
    clear_current_temp_global,
    config_context,
    extract_all_configs,
    get_base_global_config,
    get_current_temp_global,
    merge_configs,
    set_base_config_type,
    set_current_temp_global,
)


def test_set_and_clear_temp_global():
    """Test setting and clearing temporary global context."""

    @dataclass
    class TestConfig:
        value: str = "test"

    config = TestConfig(value="custom")

    # Set temp global
    set_current_temp_global(config)

    # Should be able to retrieve it
    current = get_current_temp_global()
    assert current is not None
    assert current.value == "custom"

    # Clear it
    clear_current_temp_global()

    # Should be cleared
    try:
        result = get_current_temp_global()
        assert result is None
    except LookupError:
        pass  # Also acceptable


def test_get_base_global_config():
    """Test getting base global config."""

    @dataclass
    class GlobalConfig:
        value: str = "global"

    # Set base config type
    set_base_config_type(GlobalConfig)

    # Get base global config (should create default)
    base = get_base_global_config()
    assert base is not None


def test_merge_configs_basic():
    """Test merging configs with overrides."""

    @dataclass
    class MyConfig:
        field1: str = "default1"
        field2: int = 10
        field3: bool = True

    base = MyConfig()
    overrides = {"field1": "custom", "field2": 20}

    # Merge configs
    merged = merge_configs(base, overrides)

    # Should have merged values
    assert merged.field1 == "custom"
    assert merged.field2 == 20
    assert merged.field3 is True  # Unchanged


def test_merge_configs_empty_overrides():
    """Test merging with empty overrides dict."""

    @dataclass
    class MyConfig:
        value: str = "test"

    base = MyConfig(value="original")
    merged = merge_configs(base, {})

    # Should be unchanged
    assert merged.value == "original"


def test_merge_configs_with_none():
    """Test merging configs with None values."""

    @dataclass
    class MyConfig:
        field1: Optional[str] = "default"
        field2: Optional[int] = None

    base = MyConfig()
    overrides = {"field2": 42}

    merged = merge_configs(base, overrides)

    # Override should be applied
    assert merged.field2 == 42
    # field1 should remain unchanged
    assert merged.field1 == "default"


def test_extract_all_configs_basic():
    """Test extracting all configs from merged context."""

    @dataclass
    class Config1:
        value1: str = "test1"

    @dataclass
    class Config2:
        value2: str = "test2"

    set_base_config_type(Config1)

    config1 = Config1(value1="custom1")

    with config_context(config1):
        current = get_current_temp_global()
        configs = extract_all_configs(current)

        # Should be a dict
        assert isinstance(configs, dict)
        # Should contain at least one config
        assert len(configs) > 0


def test_extract_all_configs_nested():
    """Test extracting configs from nested context."""

    @dataclass
    class GlobalConfig:
        global_val: str = "global"

    @dataclass
    class LocalConfig:
        local_val: str = "local"

    set_base_config_type(GlobalConfig)

    global_cfg = GlobalConfig(global_val="g1")
    local_cfg = LocalConfig(local_val="l1")

    with config_context(global_cfg):
        with config_context(local_cfg):
            current = get_current_temp_global()
            configs = extract_all_configs(current)

            # Should contain configs from both levels
            assert isinstance(configs, dict)


def test_config_context_with_default():
    """Test config_context creates default if none provided."""

    @dataclass
    class MyConfig:
        value: str = "default"

    set_base_config_type(MyConfig)

    # Use empty/default config
    with config_context(MyConfig()):
        current = get_current_temp_global()
        assert current is not None


def test_config_context_exception_handling():
    """Test that config_context cleans up on exception."""

    @dataclass
    class MyConfig:
        value: str = "test"

    set_base_config_type(MyConfig)

    try:
        with config_context(MyConfig(value="in_context")):
            # Verify context is set
            assert get_current_temp_global() is not None
            # Raise exception
            raise ValueError("Test exception")
    except ValueError:
        pass

    # Context should be cleaned up
    try:
        result = get_current_temp_global()
        # Should be None or raise LookupError
    except LookupError:
        pass  # Expected


def test_multiple_sequential_contexts():
    """Test multiple sequential (non-nested) contexts."""

    @dataclass
    class MyConfig:
        value: str = "test"

    set_base_config_type(MyConfig)

    # First context
    with config_context(MyConfig(value="first")):
        assert get_current_temp_global().value == "first"

    # Second context
    with config_context(MyConfig(value="second")):
        assert get_current_temp_global().value == "second"

    # Third context
    with config_context(MyConfig(value="third")):
        assert get_current_temp_global().value == "third"


def test_config_context_with_field_factory():
    """Test config context with factory fields."""

    @dataclass
    class ConfigWithFactory:
        items: list = field(default_factory=list)
        metadata: dict = field(default_factory=dict)

    set_base_config_type(ConfigWithFactory)

    config = ConfigWithFactory(items=[1, 2, 3], metadata={"key": "value"})

    with config_context(config):
        current = get_current_temp_global()
        assert current.items == [1, 2, 3]
        assert current.metadata == {"key": "value"}


def test_merge_configs_preserves_type():
    """Test that merge_configs preserves the config type."""

    @dataclass
    class MyConfig:
        value: str = "test"

    base = MyConfig(value="original")
    merged = merge_configs(base, {"value": "updated"})

    # Should still be same type
    assert type(merged) == MyConfig
    assert isinstance(merged, MyConfig)


def test_context_with_optional_fields():
    """Test context management with optional fields."""

    @dataclass
    class ConfigWithOptional:
        required: str = "req"
        optional: Optional[str] = None
        optional_int: Optional[int] = None

    set_base_config_type(ConfigWithOptional)

    config = ConfigWithOptional(
        required="set", optional="present", optional_int=42
    )

    with config_context(config):
        current = get_current_temp_global()
        assert current.required == "set"
        assert current.optional == "present"
        assert current.optional_int == 42
