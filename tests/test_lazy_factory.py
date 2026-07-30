"""Tests for lazy factory module."""
import sys
from dataclasses import dataclass, field, fields
from typing import Annotated, ClassVar, get_type_hints

import pytest
from annotated_types import Ge
from python_introspect import (
    AnnotatedDataclassValidationMixin,
    AnnotationValidationError,
    optional_member_type,
)

from objectstate import (
    LazyDataclassFactory,
    get_base_type_for_lazy,
    patch_lazy_constructors,
    register_lazy_type_mapping,
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


def test_make_lazy_simple_reuses_the_registered_nominal_type() -> None:
    @dataclass
    class SimpleConfig:
        value: str = "default"

    first = LazyDataclassFactory.make_lazy_simple(SimpleConfig)
    second = LazyDataclassFactory.make_lazy_simple(SimpleConfig)

    assert second is first
    with pytest.raises(ValueError, match="already owns lazy type"):
        LazyDataclassFactory.make_lazy_simple(
            SimpleConfig,
            lazy_class_name="AlternativeSimpleConfig",
        )


def test_none_default_rebuild_resolves_self_reference_before_module_binding() -> None:
    from objectstate.lazy_factory import (
        get_inherited_field_names,
        rebuild_with_none_defaults,
    )

    @dataclass
    class BaseConfig:
        inherited: str = "base"

    def rebuild_during_decoration(config_type):
        return rebuild_with_none_defaults(
            config_type,
            get_inherited_field_names(config_type),
        )

    @rebuild_during_decoration
    @dataclass
    class StreamingConfig(BaseConfig):
        registry: ClassVar[dict[str, type["StreamingConfig"]]] = {}
        own: str = "own"

    assert StreamingConfig.registry == {}
    assert StreamingConfig().inherited is None


def test_none_default_rebuild_preserves_declaration_metadata_and_validation() -> None:
    from objectstate.lazy_factory import rebuild_with_none_defaults

    @dataclass
    class ValidatedConfig(AnnotatedDataclassValidationMixin):
        """Authoritative rationale for the validated configuration."""

        workers: Annotated[int, Ge(1)] = 1

    rebuilt = rebuild_with_none_defaults(ValidatedConfig, set())

    assert rebuilt.__doc__ == ValidatedConfig.__doc__
    assert rebuilt.__module__ == ValidatedConfig.__module__
    assert rebuilt.__qualname__ == ValidatedConfig.__qualname__
    if "__firstlineno__" in ValidatedConfig.__dict__:
        assert rebuilt.__firstlineno__ == ValidatedConfig.__firstlineno__
    with pytest.raises(AnnotationValidationError, match="must be at least 1"):
        rebuilt(workers=0)


def test_lazy_dataclass_preserves_declaration_metadata_and_validation() -> None:
    @dataclass
    class ValidatedConfig(AnnotatedDataclassValidationMixin):
        """Authoritative rationale inherited by the lazy projection."""

        port: Annotated[int, Ge(1)] = 5555

    lazy_validated_config = LazyDataclassFactory.make_lazy_simple(ValidatedConfig)

    assert lazy_validated_config.__doc__ == ValidatedConfig.__doc__
    assert lazy_validated_config.__module__ == ValidatedConfig.__module__
    if "__firstlineno__" in ValidatedConfig.__dict__:
        assert (
            lazy_validated_config.__firstlineno__
            == ValidatedConfig.__firstlineno__
        )
    assert object.__getattribute__(lazy_validated_config(), "port") is None
    with pytest.raises(AnnotationValidationError, match="must be at least 1"):
        lazy_validated_config(port=0)


def test_injected_global_config_preserves_metadata_and_validation(
    monkeypatch,
) -> None:
    from objectstate.lazy_factory import _inject_multiple_fields_into_dataclass

    @dataclass
    class GlobalMetadataValidationRoot(AnnotatedDataclassValidationMixin):
        """Authoritative rationale for the global configuration."""

        workers: Annotated[int, Ge(1)] = field(
            default=1,
            metadata={"description": "Worker count rationale."},
        )

    @dataclass
    class InjectedConstraintConfig(AnnotatedDataclassValidationMixin):
        """Authoritative rationale for the injected configuration."""

        port: Annotated[int, Ge(1)] = 5555

    module = sys.modules[__name__]
    generated_names = (
        "GlobalMetadataValidationRoot",
        "MetadataValidationRoot",
        "LazyInjectedConstraintConfig",
    )
    for generated_name in generated_names:
        monkeypatch.setattr(module, generated_name, None, raising=False)

    _inject_multiple_fields_into_dataclass(
        GlobalMetadataValidationRoot,
        [
            {
                "config_class": InjectedConstraintConfig,
                "field_name": "injected_constraint_config",
                "lazy_class_name": "LazyInjectedConstraintConfig",
            }
        ],
    )

    rebuilt_global = module.GlobalMetadataValidationRoot
    lazy_global = module.MetadataValidationRoot
    lazy_injected = module.LazyInjectedConstraintConfig

    assert rebuilt_global.__doc__ == GlobalMetadataValidationRoot.__doc__
    assert lazy_global.__doc__ == GlobalMetadataValidationRoot.__doc__
    assert lazy_injected.__doc__ == InjectedConstraintConfig.__doc__
    rebuilt_workers = next(
        item for item in fields(rebuilt_global) if item.name == "workers"
    )
    assert rebuilt_workers.metadata == {
        "description": "Worker count rationale.",
    }
    assert isinstance(
        rebuilt_global().injected_constraint_config,
        InjectedConstraintConfig,
    )
    with pytest.raises(AnnotationValidationError, match="must be at least 1"):
        rebuilt_global(workers=0)
    with pytest.raises(AnnotationValidationError, match="must be at least 1"):
        lazy_global(workers=0)
    with pytest.raises(AnnotationValidationError, match="must be at least 1"):
        lazy_injected(port=0)


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
    lazy_annotations = get_type_hints(LazyConfig, include_extras=True)
    assert optional_member_type(lazy_annotations["field1"]) is str
    assert optional_member_type(lazy_annotations["field2"]) is int
    assert optional_member_type(lazy_annotations["field3"]) is bool


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


def test_patch_lazy_constructors_uses_registered_type_mapping():
    @dataclass
    class NestedConfig:
        value: str = "nested"

    @dataclass
    class BaseConfig:
        inherited: str = "base"
        nested: NestedConfig = field(default_factory=NestedConfig)

    LazyDataclassFactory.make_lazy_simple(NestedConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(BaseConfig)

    with patch_lazy_constructors():
        candidate = LazyConfig()

    assert object.__getattribute__(candidate, "inherited") is None
    nested = object.__getattribute__(candidate, "nested")
    assert get_base_type_for_lazy(type(nested)) is NestedConfig
    assert object.__getattribute__(nested, "value") is None


def test_patch_lazy_constructors_does_not_hide_default_factory_failure():
    def fail_default():
        raise RuntimeError("default factory failed")

    @dataclass
    class LazyConfig:
        value: str = field(default_factory=fail_default)

    with patch_lazy_constructors(types=[LazyConfig]):
        with pytest.raises(RuntimeError, match="default factory failed"):
            LazyConfig()


def test_nested_lazy_dataclass():
    """Test creating lazy dataclass with nested dataclass fields."""
    @dataclass
    class NestedConfig:
        nested_value: str = "nested"

    @dataclass
    class ParentConfig:
        parent_value: str = "parent"
        nested: NestedConfig = None

    LazyDataclassFactory.make_lazy_simple(NestedConfig)
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


def test_lazy_from_config_uses_declared_type_not_class_name() -> None:
    @dataclass
    class ChildConfig:
        value: str = "default"

    @dataclass
    class ParentConfig:
        payload: Annotated[ChildConfig, "nested config"] = field(
            default_factory=ChildConfig
        )

    LazyDataclassFactory.make_lazy_simple(ChildConfig)
    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)
    parent = LazyParentConfig.from_config(ChildConfig(value="explicit"))

    child = object.__getattribute__(parent, "payload")
    assert get_base_type_for_lazy(type(child)) is ChildConfig
    assert object.__getattribute__(child, "value") == "explicit"


def test_lazy_from_config_rejects_ambiguous_declared_owner() -> None:
    @dataclass
    class ChildConfig:
        value: str = "default"

    @dataclass
    class ParentConfig:
        first: ChildConfig = field(default_factory=ChildConfig)
        second: ChildConfig = field(default_factory=ChildConfig)

    LazyDataclassFactory.make_lazy_simple(ChildConfig)
    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)

    with pytest.raises(TypeError, match="multiple ChildConfig fields"):
        LazyParentConfig.from_config(ChildConfig())


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
