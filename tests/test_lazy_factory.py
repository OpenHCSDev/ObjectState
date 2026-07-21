"""Tests for lazy factory module."""
import pytest
from dataclasses import dataclass, field, fields

from objectstate import (
    LazyDataclassFactory,
    register_lazy_type_mapping,
    get_base_type_for_lazy,
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


def test_lazy_resolution_without_context():
    """Test lazy resolution when no context is available."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy instance without context
    lazy = LazyConfig()

    assert lazy.value == "default"
    assert lazy.number == 42


def test_lazy_resolution_without_context_uses_default_factory():
    @dataclass
    class MyConfig:
        values: tuple[str, ...] = field(default_factory=tuple)

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    assert LazyConfig().values == ()


def test_lazy_explicit_values():
    """Test that explicitly set values are returned directly."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy with explicit values - these should always be returned
    lazy = LazyConfig(value="explicit", number=100)

    # Explicit value should be used
    assert lazy.value == "explicit"
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


def test_lazy_from_config_projects_all_dataclass_fields_generically():
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy = LazyConfig.from_config(MyConfig(value="explicit", number=100))

    assert object.__getattribute__(lazy, "value") == "explicit"
    assert object.__getattribute__(lazy, "number") == 100


def test_lazy_from_config_omits_fields_equal_to_inherited_config():
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    lazy = LazyConfig.from_config(
        MyConfig(value="explicit", number=42),
        inherited=MyConfig(),
    )

    assert object.__getattribute__(lazy, "value") == "explicit"
    assert object.__getattribute__(lazy, "number") is None


def test_lazy_from_config_rejects_lazy_and_unrelated_values():
    @dataclass
    class MyConfig:
        value: str = "default"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    with pytest.raises(TypeError, match="requires concrete MyConfig"):
        LazyConfig.from_config(LazyConfig(value="explicit"))
    with pytest.raises(TypeError, match="registered lazy type"):
        LazyConfig.from_config(object())


def test_lazy_from_config_composes_registered_nested_configs() -> None:
    @dataclass
    class ChildConfig:
        value: str = "default"

    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class ParentConfig:
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)

    parent = LazyParentConfig.from_config(ChildConfig(value="explicit"))

    child = object.__getattribute__(parent, "child_config")
    assert isinstance(child, LazyChildConfig)
    assert object.__getattribute__(child, "value") == "explicit"


def test_lazy_from_config_rejects_unknown_and_duplicate_fragments() -> None:
    @dataclass
    class ChildConfig:
        value: str = "default"

    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class ParentConfig:
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)

    with pytest.raises(ValueError, match="duplicate"):
        LazyParentConfig.from_config(ChildConfig(), ChildConfig())
    with pytest.raises(TypeError, match="concrete dataclass"):
        LazyParentConfig.from_config(LazyChildConfig())
