"""Tests for placeholder module."""
import pytest
from dataclasses import dataclass

from objectstate import (
    LazyDefaultPlaceholderService,
    LazyDataclassFactory,
    LazyResolutionDataclass,
    config_context,
    has_lazy_resolution,
)
from objectstate.lazy_factory import bind_lazy_resolution_to_class


def test_placeholder_service_creation():
    """Test creating a placeholder service."""
    service = LazyDefaultPlaceholderService()
    assert service is not None


def test_placeholder_text_generation():
    """Test generating placeholder text for a field."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    service = LazyDefaultPlaceholderService()
    concrete = MyConfig(value="inherited", number=100)

    with config_context(concrete):
        lazy = LazyConfig()

        # Try to get placeholder text
        if hasattr(service, 'get_placeholder_text'):
            from objectstate.context_manager import extract_all_configs, get_current_temp_global
            current = get_current_temp_global()
            available_configs = extract_all_configs(current)

            placeholder = service.get_placeholder_text(
                lazy,
                "value",
                available_configs
            )
            # Placeholder should provide some helpful text
            assert placeholder is not None
            assert isinstance(placeholder, str)


def test_has_lazy_resolution():
    """Test checking if a type has lazy resolution."""
    @dataclass
    class MyConfig:
        value: str = "test"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    assert has_lazy_resolution(LazyConfig)


def test_concrete_lazy_resolution_is_a_nominal_type_relationship():
    @dataclass
    class ConcreteConfig:
        value: str | None = None

    bind_lazy_resolution_to_class(ConcreteConfig)

    assert issubclass(ConcreteConfig, LazyResolutionDataclass)
    assert has_lazy_resolution(ConcreteConfig)
    assert "_has_lazy_resolution" not in vars(ConcreteConfig)
