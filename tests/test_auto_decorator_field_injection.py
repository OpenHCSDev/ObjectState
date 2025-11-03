"""Tests for @auto_create_decorator and field injection mechanism.

Tests the core decorator-driven workflow that is essential for building
hierarchical configs in a clean, composable way.
"""

import sys
from dataclasses import dataclass, fields

from hieraconf import (
    LazyDataclassFactory,
    auto_create_decorator,
    set_base_config_type,
)
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_auto_decorator_creates_decorator_and_lazy_class():
    """Test @auto_create_decorator creates both decorator and lazy class."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalTestConfig:
        base_value: int = 1

    # Should create global_test_config decorator
    module = sys.modules[GlobalTestConfig.__module__]
    assert hasattr(
        module, "global_test_config"
    ), "Decorator should be exported as global_test_config"

    # Get the decorator
    global_test_config = getattr(module, "global_test_config")
    assert callable(
        global_test_config
    ), "global_test_config should be callable"


def test_field_injection_basic():
    """Test that decorated classes get injected as fields into global config.

    This is the core mechanism for building hierarchical configs.
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalAppConfig:
        app_name: str = "test"

    module = sys.modules[GlobalAppConfig.__module__]
    global_app_config = getattr(module, "global_app_config")

    # Decorate another config
    @global_app_config
    @dataclass(frozen=True)
    class DatabaseConfig:
        host: str = "localhost"
        port: int = 5432

    # Trigger injection
    _inject_all_pending_fields()

    # GlobalAppConfig should now have database_config field
    assert hasattr(
        GlobalAppConfig, "__dataclass_fields__"
    ), "GlobalAppConfig should be a dataclass"

    field_names = {f.name for f in fields(GlobalAppConfig)}
    assert (
        "database_config" in field_names
    ), "database_config should be injected as field"


def test_field_injection_creates_lazy_class():
    """Test that field injection creates lazy versions of decorated classes."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator
    @dataclass(frozen=True)
    class ComponentConfig:
        comp_value: int = 10

    _inject_all_pending_fields()

    # Should create LazyComponentConfig
    LazyComponentConfig = getattr(module, "LazyComponentConfig", None)
    assert (
        LazyComponentConfig is not None
    ), "LazyComponentConfig should be created and exported"

    # Should be a valid lazy class
    assert hasattr(
        LazyComponentConfig, "__dataclass_fields__"
    ), "LazyComponentConfig should be a dataclass"


def test_field_injection_with_ui_hidden():
    """Test field injection with ui_hidden parameter.

    ui_hidden controls whether a config appears in the UI, but should not
    affect lazy resolution or field injection.
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig:
        hidden_value: str = "hidden"

    # Should have _ui_hidden marker before injection
    assert hasattr(
        HiddenConfig, "_ui_hidden"
    ), "HiddenConfig should have _ui_hidden marker"
    assert (
        HiddenConfig._ui_hidden is True
    ), "_ui_hidden should be True"

    _inject_all_pending_fields()

    # Lazy version should also be hidden
    LazyHiddenConfig = getattr(module, "LazyHiddenConfig", None)
    assert (
        LazyHiddenConfig is not None
    ), "LazyHiddenConfig should exist even if ui_hidden"

    assert hasattr(
        LazyHiddenConfig, "_ui_hidden"
    ), "LazyHiddenConfig should have _ui_hidden marker"
    assert (
        LazyHiddenConfig._ui_hidden is True
    ), "LazyHiddenConfig._ui_hidden should be True"


def test_field_injection_with_optional():
    """Test field injection with optional parameter.

    optional=True should wrap the field type with Optional.
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(optional=True)
    @dataclass(frozen=True)
    class OptionalConfig:
        opt_value: str = "optional"

    _inject_all_pending_fields()

    # GlobalConfig should now have optional_config field
    field_names = {f.name for f in fields(GlobalConfig)}
    assert (
        "optional_config" in field_names
    ), "optional_config should be injected as field"


def test_multiple_decorators_in_hierarchy():
    """Test using decorator on multiple configs in a hierarchy."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        base_value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator
    @dataclass(frozen=True)
    class DatabaseConfig:
        host: str = "localhost"

    @global_config_decorator
    @dataclass(frozen=True)
    class CacheConfig:
        ttl: int = 300

    _inject_all_pending_fields()

    # Both should be injected
    field_names = {f.name for f in fields(GlobalConfig)}
    assert (
        "database_config" in field_names
    ), "database_config should be injected"
    assert (
        "cache_config" in field_names
    ), "cache_config should be injected"


def test_abstract_classes_not_injected():
    """Test that abstract classes are not injected into global config.

    Abstract classes can't be instantiated, so they shouldn't be injected
    as fields (they would cause instantiation errors).
    """
    from abc import ABC, abstractmethod

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator
    @dataclass(frozen=True)
    class AbstractConfig(ABC):
        @abstractmethod
        def do_something(self):
            pass

    _inject_all_pending_fields()

    # AbstractConfig should NOT be injected (can't instantiate)
    field_names = {f.name for f in fields(GlobalConfig)}
    assert (
        "abstract_config" not in field_names
    ), "Abstract classes should not be injected"

    # But lazy version should still exist
    LazyAbstractConfig = getattr(module, "LazyAbstractConfig", None)
    assert (
        LazyAbstractConfig is not None
    ), "LazyAbstractConfig should exist"


def test_lazy_resolution_after_field_injection():
    """Test that lazy configs work correctly after field injection."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    module = sys.modules[GlobalPipelineConfig.__module__]
    global_pipeline_config = getattr(module, "global_pipeline_config")

    @global_pipeline_config
    @dataclass(frozen=True)
    class PathPlanningConfig:
        output_suffix: str = "_plan"

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Create concrete instances
    global_config = GlobalPipelineConfig(num_workers=4, output_dir="/data")
    path_config = PathPlanningConfig(output_suffix="_custom")

    # Use lazy config
    from hieraconf import config_context

    LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(
        GlobalPipelineConfig
    )

    with config_context(global_config):
        with config_context(path_config):
            lazy = LazyPipelineConfig()
            # Should resolve from global context
            assert lazy.num_workers == 4
            assert lazy.output_dir == "/data"


def test_decorator_naming_convention():
    """Test that decorator follows snake_case naming convention.

    GlobalTestConfig → global_test_config
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalMyLongConfigName:
        value: int = 1

    module = sys.modules[GlobalMyLongConfigName.__module__]

    # Decorator name should be snake_case version
    assert hasattr(
        module, "global_my_long_config_name"
    ), "Decorator should use snake_case naming"


def test_field_injection_only_applies_to_global_prefix():
    """Test that @auto_create_decorator requires GlobalXxx naming convention."""

    # Should work with Global prefix
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalValidName:
        value: int = 1

    # Should fail without Global prefix
    try:
        @auto_create_decorator
        @dataclass(frozen=True)
        class NotGlobalConfig:
            value: int = 1

        assert False, "Should require Global prefix"
    except ValueError as e:
        assert "Global" in str(e)
        assert "prefix" in str(e)
