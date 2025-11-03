"""Tests for ui_hidden parameter.

The ui_hidden parameter controls whether a configuration appears in the UI,
while keeping it available for lazy resolution in the background.
"""

import sys
from dataclasses import dataclass

from hieraconf import (
    LazyDataclassFactory,
    auto_create_decorator,
    config_context,
    set_base_config_type,
)
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_ui_hidden_marks_config_with_metadata():
    """Test that ui_hidden parameter marks config with _ui_hidden attribute."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig:
        hidden_value: str = "hidden"

    # Should have _ui_hidden marker
    assert hasattr(
        HiddenConfig, "_ui_hidden"
    ), "HiddenConfig should have _ui_hidden attribute"
    assert (
        HiddenConfig._ui_hidden is True
    ), "_ui_hidden should be True"


def test_ui_hidden_lazy_class_also_marked():
    """Test that lazy versions of ui_hidden configs are also marked."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig:
        hidden_value: str = "hidden"

    _inject_all_pending_fields()

    # Get lazy version
    LazyHiddenConfig = getattr(module, "LazyHiddenConfig")

    # Should also be marked
    assert hasattr(
        LazyHiddenConfig, "_ui_hidden"
    ), "LazyHiddenConfig should have _ui_hidden attribute"
    assert (
        LazyHiddenConfig._ui_hidden is True
    ), "LazyHiddenConfig._ui_hidden should be True"


def test_ui_hidden_false_not_marked():
    """Test that configs with ui_hidden=False are not marked."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=False)
    @dataclass(frozen=True)
    class VisibleConfig:
        visible_value: str = "visible"

    _inject_all_pending_fields()

    # Should not have _ui_hidden or should be False
    has_ui_hidden = hasattr(VisibleConfig, "_ui_hidden")
    if has_ui_hidden:
        assert (
            VisibleConfig._ui_hidden is False
        ), "Should have _ui_hidden=False"
    # If no attribute at all, that's also fine


def test_ui_hidden_default_is_false():
    """Test that ui_hidden defaults to False."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    # Don't specify ui_hidden
    @global_config
    @dataclass(frozen=True)
    class DefaultConfig:
        value_field: str = "default"

    _inject_all_pending_fields()

    # Should not have _ui_hidden marker (or should be False)
    has_ui_hidden = hasattr(DefaultConfig, "_ui_hidden")
    if has_ui_hidden:
        assert (
            DefaultConfig._ui_hidden is False
        ), "ui_hidden should default to False"


def test_ui_hidden_does_not_affect_lazy_resolution():
    """Test that ui_hidden doesn't prevent lazy resolution.

    Configs marked as ui_hidden should still resolve lazily, they just
    don't appear in the UI.
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    module = sys.modules[GlobalPipelineConfig.__module__]
    global_config = getattr(module, "global_pipeline_config")

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Create concrete config
    global_config_obj = GlobalPipelineConfig(num_workers=4, output_dir="/data")

    # Create lazy config
    LazyHiddenPipelineConfig = LazyDataclassFactory.make_lazy_simple(
        HiddenPipelineConfig
    )

    # Lazy resolution should work even though ui_hidden=True
    with config_context(global_config_obj):
        lazy = LazyHiddenPipelineConfig()
        assert lazy.num_workers == 4
        assert lazy.output_dir == "/data"


def test_ui_hidden_with_inherit_as_none():
    """Test ui_hidden combined with inherit_as_none.

    Both parameters should work together without issues.
    """

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=True, inherit_as_none=True)
    @dataclass(frozen=True)
    class HiddenAndNoneConfig(BaseConfig):
        explicit_field: str = "explicit"

    _inject_all_pending_fields()

    # Create instance
    config = HiddenAndNoneConfig()

    # inherit_as_none should work
    assert (
        config.base_field is None
    ), "Inherited field should be None"
    assert (
        config.explicit_field == "explicit"
    ), "Explicit field should have default"

    # Should have ui_hidden marker
    assert hasattr(
        HiddenAndNoneConfig, "_ui_hidden"
    ), "Should have ui_hidden marker"


def test_ui_hidden_with_optional():
    """Test ui_hidden combined with optional parameter."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=True, optional=True)
    @dataclass(frozen=True)
    class HiddenOptionalConfig:
        opt_value: str = "optional"

    _inject_all_pending_fields()

    # Both should work together
    LazyHiddenOptionalConfig = getattr(module, "LazyHiddenOptionalConfig")

    assert (
        LazyHiddenOptionalConfig is not None
    ), "Lazy class should exist"
    assert hasattr(
        LazyHiddenOptionalConfig, "_ui_hidden"
    ), "Should have ui_hidden marker"


def test_multiple_ui_hidden_configs():
    """Test multiple ui_hidden configs in same hierarchy."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig1:
        val1: str = "h1"

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig2:
        val2: str = "h2"

    @global_config(ui_hidden=False)
    @dataclass(frozen=True)
    class VisibleConfig:
        val3: str = "v3"

    _inject_all_pending_fields()

    # Check markers
    assert hasattr(HiddenConfig1, "_ui_hidden")
    assert hasattr(HiddenConfig2, "_ui_hidden")

    # VisibleConfig may or may not have marker
    if hasattr(VisibleConfig, "_ui_hidden"):
        assert VisibleConfig._ui_hidden is False


def test_ui_hidden_queried_by_ui_layer():
    """Test that UI layer can check ui_hidden marker to decide rendering.

    This simulates how the UI would use this metadata to filter what to show.
    """

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    configs_to_decorate = []

    @global_config(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig:
        hidden_value: str = "hidden"

    configs_to_decorate.append(("HiddenConfig", HiddenConfig))

    @global_config(ui_hidden=False)
    @dataclass(frozen=True)
    class VisibleConfig:
        visible_value: str = "visible"

    configs_to_decorate.append(("VisibleConfig", VisibleConfig))

    _inject_all_pending_fields()

    # Simulate UI filtering
    visible_to_ui = []
    for config_name, config_class in configs_to_decorate:
        is_hidden = getattr(config_class, "_ui_hidden", False)
        if not is_hidden:
            visible_to_ui.append(config_name)

    # Only VisibleConfig should be in UI list
    assert (
        "VisibleConfig" in visible_to_ui
    ), "VisibleConfig should be visible to UI"
    assert (
        "HiddenConfig" not in visible_to_ui
    ), "HiddenConfig should not be visible to UI"
