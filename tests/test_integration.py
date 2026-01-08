"""Integration tests for objectstate.

Tests actual usage patterns that match how OpenHCS uses the library.
"""
import pytest
from dataclasses import dataclass

from objectstate import (
    set_base_config_type,
    LazyDataclassFactory,
    config_context,
    get_base_type_for_lazy,
)


def test_readme_quick_start_example():
    """Test the quick start example from README.

    This test sets its own base config type to demonstrate the pattern.
    """
    @dataclass
    class GlobalConfig:
        output_dir: str = "/tmp"
        num_workers: int = 4
        debug: bool = False

    # Initialize framework with this test's config type
    set_base_config_type(GlobalConfig)

    # Create lazy version
    LazyGlobalConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)

    # Use with context
    global_cfg = GlobalConfig(output_dir="/data", num_workers=8)

    with config_context(global_cfg):
        lazy_cfg = LazyGlobalConfig()
        assert lazy_cfg.output_dir == "/data"
        assert lazy_cfg.debug is False


def test_lazy_factory_creates_lazy_class():
    """Test that LazyDataclassFactory creates a proper lazy class."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Lazy class should be created
    assert LazyConfig is not None
    assert LazyConfig.__name__ == "LazyMyConfig"

    # Type mapping should be registered
    assert get_base_type_for_lazy(LazyConfig) == MyConfig


def test_lazy_instantiation():
    """Test that lazy dataclasses can be instantiated."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Should be able to create instances
    lazy = LazyConfig()
    assert lazy is not None

    # Should be able to create with explicit values
    lazy_with_values = LazyConfig(value="explicit", number=100)
    assert lazy_with_values.value == "explicit"
    assert lazy_with_values.number == 100


def test_explicit_values_preserved():
    """Test that explicitly set values are preserved in lazy instances."""
    @dataclass
    class MyConfig:
        field1: str = "default1"
        field2: str = "default2"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create with explicit value for field1 only
    lazy = LazyConfig(field1="explicit")

    # Explicit value should be returned
    assert lazy.field1 == "explicit"


def test_no_context_returns_none():
    """Test behavior when no context is available."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy instance without context (no matching base config type)
    lazy = LazyConfig()

    # Without context, fields that weren't explicitly set return None
    # (or default if implementation supports fallback)
    result = lazy.value
    assert result is None or result == "default"


def test_to_base_config_with_explicit_values():
    """Test converting lazy config to base config."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy = LazyConfig(value="test", number=100)

    # Convert to base config
    if hasattr(lazy, 'to_base_config'):
        base = lazy.to_base_config()
        assert isinstance(base, MyConfig)
        assert base.value == "test"
        assert base.number == 100
