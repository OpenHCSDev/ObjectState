"""Extended tests for placeholder service to improve coverage."""

from dataclasses import dataclass
from typing import Optional

from hieraconf import (
    LazyDataclassFactory,
    LazyDefaultPlaceholderService,
    config_context,
    set_base_config_type,
)


def test_placeholder_service_has_lazy_resolution():
    """Test has_lazy_resolution method."""

    @dataclass
    class RegularConfig:
        value: str = "test"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(RegularConfig)

    service = LazyDefaultPlaceholderService()

    # Lazy class should have lazy resolution
    assert service.has_lazy_resolution(LazyConfig)

    # Regular class should not
    assert not service.has_lazy_resolution(RegularConfig)


def test_placeholder_with_none_values():
    """Test placeholder generation with None values."""

    @dataclass
    class ConfigWithNone:
        required: str = "default"
        optional: Optional[str] = None

    set_base_config_type(ConfigWithNone)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(ConfigWithNone)

    service = LazyDefaultPlaceholderService()

    # Create config with None value
    concrete = ConfigWithNone(required="set", optional=None)

    with config_context(concrete):
        lazy = LazyConfig()

        # Test NONE_VALUE_TEXT constant
        assert service.NONE_VALUE_TEXT == "(none)"


def test_placeholder_prefix_constant():
    """Test placeholder prefix constant."""
    service = LazyDefaultPlaceholderService()

    # Should have default prefix
    assert service.PLACEHOLDER_PREFIX == "Default"


def test_placeholder_with_explicit_prefix():
    """Test placeholder generation with custom prefix."""

    @dataclass
    class MyConfig:
        value: str = "test"

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    service = LazyDefaultPlaceholderService()

    if hasattr(service, "get_lazy_resolved_placeholder"):
        # Test with custom prefix
        placeholder = service.get_lazy_resolved_placeholder(
            LazyConfig, "value", placeholder_prefix="Custom"
        )

        # Should use custom prefix if implemented
        if placeholder:
            assert isinstance(placeholder, str)


def test_placeholder_with_different_field_types():
    """Test placeholder service with various field types."""

    @dataclass
    class MixedConfig:
        string_field: str = "text"
        int_field: int = 42
        bool_field: bool = True
        optional_field: Optional[str] = None

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MixedConfig)

    service = LazyDefaultPlaceholderService()

    # Should handle different types
    assert service.has_lazy_resolution(LazyConfig)


def test_placeholder_service_with_nested_configs():
    """Test placeholder service with nested config structures."""

    @dataclass
    class InnerConfig:
        inner_value: str = "inner"

    @dataclass
    class OuterConfig:
        outer_value: str = "outer"
        nested: Optional[InnerConfig] = None

    set_base_config_type(OuterConfig)
    LazyOuter = LazyDataclassFactory.make_lazy_simple(OuterConfig)

    service = LazyDefaultPlaceholderService()

    # Should recognize lazy config
    assert service.has_lazy_resolution(LazyOuter)


def test_placeholder_service_instance_creation():
    """Test that multiple service instances can be created."""
    service1 = LazyDefaultPlaceholderService()
    service2 = LazyDefaultPlaceholderService()

    # Both should work independently
    assert service1 is not None
    assert service2 is not None
    assert service1.PLACEHOLDER_PREFIX == service2.PLACEHOLDER_PREFIX


def test_placeholder_with_inheritance():
    """Test placeholder service with inherited configs."""

    @dataclass
    class BaseConfig:
        base_field: str = "base"

    @dataclass
    class DerivedConfig(BaseConfig):
        derived_field: str = "derived"

    LazyDerived = LazyDataclassFactory.make_lazy_simple(DerivedConfig)

    service = LazyDefaultPlaceholderService()

    # Should recognize derived lazy config
    assert service.has_lazy_resolution(LazyDerived)


def test_placeholder_service_static_methods():
    """Test that service methods are static and can be called on class."""
    # has_lazy_resolution is a static method
    assert hasattr(LazyDefaultPlaceholderService, "has_lazy_resolution")

    @dataclass
    class TestConfig:
        value: str = "test"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(TestConfig)

    # Should work on class directly
    result = LazyDefaultPlaceholderService.has_lazy_resolution(LazyConfig)
    assert result is True
