"""Tests for inherit_as_none parameter and multiple inheritance patterns.

The inherit_as_none parameter is critical for proper lazy resolution with
multiple inheritance and abstract base classes, as used extensively in OpenHCS.
"""

import sys
from abc import ABC
from dataclasses import dataclass, fields
from typing import Optional, Union, List

from hieraconf import (
    auto_create_decorator,
    set_base_config_type,
)
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_inherit_as_none_sets_inherited_fields_to_none():
    """Test inherit_as_none parameter sets inherited fields to None.

    When inherit_as_none=True (default), inherited fields get None as default
    instead of inheriting parent's default value.
    """

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base_default"
        shared_field: int = 100

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        global_field: str = "global"

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        child_field: str = "child"

    _inject_all_pending_fields()

    # Create instance with defaults
    child = ChildConfig()

    # Inherited fields should have None defaults
    assert (
        child.base_field is None
    ), "Inherited base_field should be None with inherit_as_none=True"
    assert (
        child.shared_field is None
    ), "Inherited shared_field should be None with inherit_as_none=True"

    # Explicit field keeps default
    assert (
        child.child_field == "child"
    ), "Explicit child_field should keep its default"


def test_inherit_as_none_false_keeps_parent_defaults():
    """Test inherit_as_none=False keeps parent defaults."""

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base_default"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=False)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        child_field: str = "child"

    _inject_all_pending_fields()

    child = ChildConfig()

    # With inherit_as_none=False, should keep parent's default
    assert (
        child.base_field == "base_default"
    ), "Should keep parent default with inherit_as_none=False"
    assert (
        child.child_field == "child"
    ), "Explicit field should keep its default"


def test_multiple_inheritance_with_inherit_as_none():
    """Test inherit_as_none with multiple inheritance (OpenHCS pattern).

    This mirrors openhcs/core/config.py:443-452 where StreamingConfig inherits
    from multiple parents and uses inherit_as_none to clear inherited fields.
    """

    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None
        well_filter_mode: str = "include"

    @dataclass(frozen=True)
    class StreamingDefaults:
        persistent: bool = True
        host: str = "localhost"
        port: int = 5555

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        num_workers: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(ui_hidden=True, inherit_as_none=True)
    @dataclass(frozen=True)
    class StreamingConfig(WellFilterConfig, StreamingDefaults):
        pass

    _inject_all_pending_fields()

    # Create instance with defaults
    streaming = StreamingConfig()

    # All inherited fields should be None
    assert (
        streaming.well_filter is None
    ), "well_filter should be None"
    assert (
        streaming.well_filter_mode is None
    ), "well_filter_mode should be None"
    assert (
        streaming.persistent is None
    ), "persistent should be None"
    assert (
        streaming.host is None
    ), "host should be None"
    assert (
        streaming.port is None
    ), "port should be None"


def test_inherit_as_none_with_explicit_overrides():
    """Test that explicit field definitions are not overridden by inherit_as_none."""

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base"
        override_me: int = 100

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        # Explicitly redefine override_me with new default
        override_me: int = 999

    _inject_all_pending_fields()

    child = ChildConfig()

    # Inherited but not explicitly redefined should be None
    assert (
        child.base_field is None
    ), "Non-explicit inherited field should be None"

    # Explicitly redefined field should keep its new default
    assert (
        child.override_me == 999
    ), "Explicit override should be preserved"


def test_inherit_as_none_with_abc():
    """Test inherit_as_none with abstract base classes.

    This is the pattern used in OpenHCS for abstract config hierarchies.
    """

    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None
        well_filter_mode: str = "include"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        num_workers: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(ui_hidden=True, inherit_as_none=True)
    @dataclass(frozen=True)
    class AbstractStepConfig(WellFilterConfig, ABC):
        pass

    # Concrete implementation should be injectable
    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ConcreteStepConfig(AbstractStepConfig):
        step_name: str = "default"

    _inject_all_pending_fields()

    # Concrete should be instantiable
    concrete = ConcreteStepConfig()
    assert (
        concrete.well_filter is None
    ), "well_filter should be None"
    assert (
        concrete.well_filter_mode is None
    ), "well_filter_mode should be None"
    assert (
        concrete.step_name == "default"
    ), "Explicit field should be present"


def test_inherit_as_none_preserves_type_annotations():
    """Test that inherit_as_none preserves field type annotations."""

    @dataclass(frozen=True)
    class BaseConfig:
        count: int = 10
        items: Optional[List[str]] = None

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        pass

    _inject_all_pending_fields()

    # Check that fields have correct types
    field_types = {f.name: f.type for f in fields(ChildConfig)}

    assert (
        field_types["count"] == int
    ), "count should have int type"
    # items should have List[str] or Optional[List[str]] depending on annotation
    assert (
        "List" in str(field_types["items"]) or "list" in str(field_types["items"]).lower()
    ), "items should have List type annotation"


def test_inherit_as_none_with_nested_inheritance():
    """Test inherit_as_none with nested inheritance chains."""

    @dataclass(frozen=True)
    class LevelOneConfig:
        level_one_field: str = "l1"

    @dataclass(frozen=True)
    class LevelTwoConfig(LevelOneConfig):
        level_two_field: str = "l2"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class LevelThreeConfig(LevelTwoConfig):
        level_three_field: str = "l3"

    _inject_all_pending_fields()

    config = LevelThreeConfig()

    # All inherited fields should be None
    assert (
        config.level_one_field is None
    ), "level_one_field should be None"
    assert (
        config.level_two_field is None
    ), "level_two_field should be None"
    # Explicit field keeps default
    assert (
        config.level_three_field == "l3"
    ), "level_three_field should be 'l3'"


def test_inherit_as_none_with_optional_types():
    """Test that inherit_as_none works correctly with Optional types."""

    @dataclass(frozen=True)
    class BaseConfig:
        optional_str: Optional[str] = "default"
        required_str: str = "default"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        pass

    _inject_all_pending_fields()

    child = ChildConfig()

    # Both should be None even though one is Optional
    assert (
        child.optional_str is None
    ), "Optional inherited field should be None"
    assert (
        child.required_str is None
    ), "Non-optional inherited field should still be None"


def test_inherit_as_none_default_is_true():
    """Test that inherit_as_none defaults to True."""

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, "global_config")

    # Don't specify inherit_as_none - should default to True
    @global_config_decorator
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        child_field: str = "child"

    _inject_all_pending_fields()

    child = ChildConfig()

    # Should default to inherit_as_none=True behavior
    assert (
        child.base_field is None
    ), "Should default to inherit_as_none=True"
    assert (
        child.child_field == "child"
    ), "Explicit field should keep default"
