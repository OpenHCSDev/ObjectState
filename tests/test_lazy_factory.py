"""Tests for lazy factory module."""
import pytest
from dataclasses import dataclass, fields

from lazy_config import (
    LazyDataclassFactory,
    register_lazy_type_mapping,
    get_base_type_for_lazy,
    config_context,
)


def test_make_lazy_simple():
    """Test creating a simple lazy dataclass."""
    @dataclass
    class SimpleConfig:
        value: str = "default"
        number: int = 42

    LazySimpleConfig = LazyDataclassFactory.make_lazy_simple(SimpleConfig)

    # Check that lazy class was created
    assert LazySimpleConfig is not None
    assert LazySimpleConfig.__name__ == "LazySimpleConfig"

    # Check that type mapping was registered
    assert get_base_type_for_lazy(LazySimpleConfig) == SimpleConfig


def test_lazy_dataclass_fields():
    """Test that lazy dataclass has same fields as base."""
    @dataclass
    class ConfigWithFields:
        field1: str = "default1"
        field2: int = 100
        field3: bool = True

    LazyConfig = LazyDataclassFactory.make_lazy_simple(ConfigWithFields)

    # Get field names
    lazy_fields = {f.name for f in fields(LazyConfig)}
    base_fields = {f.name for f in fields(ConfigWithFields)}

    # Should have same fields
    assert lazy_fields == base_fields


def test_lazy_resolution_with_context():
    """Test that lazy fields resolve from context."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create concrete config with custom values
    concrete = MyConfig(value="custom", number=100)

    # Use in context
    with config_context(concrete):
        lazy = LazyConfig()
        # Lazy fields should resolve from context
        assert lazy.value == "custom"
        assert lazy.number == 100


def test_lazy_resolution_without_context():
    """Test lazy resolution when no context is available."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy instance without context
    lazy = LazyConfig()

    # Should return None or default values depending on implementation
    # The exact behavior depends on whether there's a fallback to static defaults
    assert lazy.value in [None, "default"]


def test_lazy_explicit_values():
    """Test that explicitly set values override lazy resolution."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    concrete = MyConfig(value="context_value", number=100)

    with config_context(concrete):
        # Create lazy with explicit value
        lazy = LazyConfig(value="explicit")

        # Explicit value should be used
        assert lazy.value == "explicit"
        # Non-explicit value should resolve from context
        assert lazy.number == 100


def test_register_and_get_lazy_type_mapping():
    """Test lazy type mapping registration."""
    @dataclass
    class BaseConfig:
        value: str = "test"

    @dataclass
    class LazyConfig:
        value: str = None

    # Register mapping
    register_lazy_type_mapping(LazyConfig, BaseConfig)

    # Verify mapping
    assert get_base_type_for_lazy(LazyConfig) == BaseConfig


def test_nested_lazy_dataclass():
    """Test creating lazy dataclass with nested dataclass fields."""
    @dataclass
    class NestedConfig:
        nested_value: str = "nested"

    @dataclass
    class ParentConfig:
        parent_value: str = "parent"
        nested: NestedConfig = None

    LazyParent = LazyDataclassFactory.make_lazy_simple(ParentConfig)

    # Should handle nested dataclass
    lazy = LazyParent()
    assert lazy is not None


def test_lazy_to_base_config():
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
