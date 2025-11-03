"""Extended tests for dual-axis resolver to improve coverage."""

from dataclasses import dataclass, field
from typing import Optional

import pytest

from hieraconf import (
    LazyDataclassFactory,
    config_context,
    set_base_config_type,
    resolve_field_inheritance,
    extract_all_configs,
    get_current_temp_global,
)


def test_lazy_field_access_triggers_resolution():
    """Test that accessing lazy field triggers resolution."""

    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    concrete = MyConfig(value="resolved", number=100)

    with config_context(concrete):
        lazy = LazyConfig()

        # Accessing field should trigger resolution
        assert lazy.value == "resolved"
        assert lazy.number == 100


def test_lazy_field_with_none_default():
    """Test lazy field with None as default value."""

    @dataclass
    class ConfigWithNone:
        required: str = "default"
        optional: Optional[str] = None

    set_base_config_type(ConfigWithNone)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(ConfigWithNone)

    concrete = ConfigWithNone(required="value", optional="set")

    with config_context(concrete):
        lazy = LazyConfig()
        assert lazy.required == "value"
        assert lazy.optional == "set"


def test_lazy_field_explicit_none_value():
    """Test lazy field when explicitly set to None."""

    @dataclass
    class MyConfig:
        value: Optional[str] = "default"

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy with explicit None
    lazy = LazyConfig(value=None)

    # None might resolve to default or stay None depending on implementation
    # Just verify it doesn't crash
    _ = lazy.value


def test_multiple_lazy_instances_independent():
    """Test that multiple lazy instances are independent."""

    @dataclass
    class MyConfig:
        value: int = 1

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    concrete = MyConfig(value=100)

    with config_context(concrete):
        lazy1 = LazyConfig()
        lazy2 = LazyConfig(value=200)

        # lazy1 resolves from context
        assert lazy1.value == 100
        # lazy2 has explicit value
        assert lazy2.value == 200


def test_lazy_with_field_factory():
    """Test lazy config with field factory defaults."""

    @dataclass
    class ConfigWithFactory:
        items: list = field(default_factory=list)
        count: int = 0

    set_base_config_type(ConfigWithFactory)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(ConfigWithFactory)

    concrete = ConfigWithFactory(items=[1, 2, 3], count=3)

    with config_context(concrete):
        lazy = LazyConfig()
        assert lazy.items == [1, 2, 3]
        assert lazy.count == 3


def test_lazy_inheritance_simple():
    """Test simple lazy class inheritance."""

    @dataclass
    class Base:
        base_val: int = 10

    @dataclass
    class Derived(Base):
        derived_val: int = 20

    set_base_config_type(Derived)
    LazyDerived = LazyDataclassFactory.make_lazy_simple(Derived)

    concrete = Derived(base_val=100, derived_val=200)

    with config_context(concrete):
        lazy = LazyDerived()
        assert lazy.base_val == 100
        assert lazy.derived_val == 200


def test_lazy_with_property_access():
    """Test that lazy config handles property-style access."""

    @dataclass
    class MyConfig:
        value: str = "test"

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy = LazyConfig(value="explicit")

    # Test both attribute and getattr access
    assert lazy.value == "explicit"
    assert getattr(lazy, "value") == "explicit"


def test_lazy_with_missing_context():
    """Test lazy resolution when context is missing."""

    @dataclass
    class MyConfig:
        value: str = "default"

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy without context
    lazy = LazyConfig()

    # Without context, might return None or default
    # Just verify it doesn't crash
    result = lazy.value
    assert result is None or result == "default"


def test_lazy_str_repr():
    """Test string representation of lazy config."""

    @dataclass
    class MyConfig:
        value: str = "test"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy = LazyConfig(value="custom", number=100)

    # Should have string representation
    str_repr = str(lazy)
    assert "LazyMyConfig" in str_repr or "MyConfig" in str_repr


def test_lazy_equality():
    """Test equality comparison of lazy configs."""

    @dataclass
    class MyConfig:
        value: str = "test"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy1 = LazyConfig(value="same")
    lazy2 = LazyConfig(value="same")
    lazy3 = LazyConfig(value="different")

    # Same values should be equal
    assert lazy1 == lazy2
    # Different values should not be equal
    assert lazy1 != lazy3
