"""Tests for automatic nested dataclass lazification.

When a config has a field with a dataclass type, the framework automatically
converts that field type to a lazy version for proper resolution in contexts.
This is a critical feature that enables hierarchical lazy resolution.
"""

import sys
from dataclasses import dataclass
from typing import Optional

from hieraconf import (
    LazyDataclassFactory,
    auto_create_decorator,
    config_context,
    set_base_config_type,
)
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_nested_dataclass_creates_lazy_version():
    """Test that nested dataclass fields automatically get lazy versions."""

    @dataclass(frozen=True)
    class PathPlanningConfig:
        output_dir_suffix: str = "_openhcs"
        sub_dir: str = "images"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        # This field should automatically have LazyPathPlanningConfig created for it
        path_planning_config: Optional[PathPlanningConfig] = None

    module = sys.modules[GlobalPipelineConfig.__module__]
    global_pipeline_config = getattr(module, "global_pipeline_config")

    @global_pipeline_config
    @dataclass(frozen=True)
    class PathPlanningConfigNested:
        output_dir_suffix: str = "_openhcs"
        sub_dir: str = "images"

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Should have created LazyPathPlanningConfigNested
    LazyPathPlanningConfigNested = getattr(
        module, "LazyPathPlanningConfigNested", None
    )
    assert (
        LazyPathPlanningConfigNested is not None
    ), "Lazy version should be created automatically"


def test_nested_config_lazy_resolution():
    """Test that nested configs resolve lazily within context."""

    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None
        well_filter_mode: str = "include"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1

    module = sys.modules[GlobalPipelineConfig.__module__]
    global_pipeline_config = getattr(module, "global_pipeline_config")

    @global_pipeline_config
    @dataclass(frozen=True)
    class PathPlanningConfig(WellFilterConfig):
        output_dir_suffix: str = "_custom"

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Create configs
    global_config = GlobalPipelineConfig(num_workers=4)
    path_config = PathPlanningConfig(
        output_dir_suffix="_plan", well_filter=2, well_filter_mode="exclude"
    )

    # Create lazy path planning
    LazyPathPlanningConfig = LazyDataclassFactory.make_lazy_simple(PathPlanningConfig)

    # Lazy resolution should work with context
    with config_context(global_config):
        with config_context(path_config):
            lazy = LazyPathPlanningConfig()
            assert lazy.num_workers is None or lazy.num_workers == 4
            assert lazy.output_dir_suffix == "_plan"
            assert lazy.well_filter == 2
            assert lazy.well_filter_mode == "exclude"


def test_deeply_nested_configs():
    """Test resolution with deeply nested config hierarchy."""

    @dataclass(frozen=True)
    class BaseConfig:
        base_value: int = 1

    @dataclass(frozen=True)
    class MiddleConfig(BaseConfig):
        middle_value: str = "middle"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        global_value: int = 10

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config
    @dataclass(frozen=True)
    class DeepConfig(MiddleConfig):
        deep_value: str = "deep"

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    # Create instances with explicit values
    global_obj = GlobalConfig(global_value=100)
    deep_obj = DeepConfig(base_value=11, middle_value="m", deep_value="d")

    # Create lazy version
    LazyDeepConfig = LazyDataclassFactory.make_lazy_simple(DeepConfig)

    with config_context(global_obj):
        with config_context(deep_obj):
            lazy = LazyDeepConfig()
            assert lazy.base_value == 11
            assert lazy.middle_value == "m"
            assert lazy.deep_value == "d"


def test_nested_multiple_levels():
    """Test with multiple nested configs at different levels."""

    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None

    @dataclass(frozen=True)
    class PathPlanningConfig(WellFilterConfig):
        output_suffix: str = "_plan"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1

    module = sys.modules[GlobalPipelineConfig.__module__]
    global_pipeline_config = getattr(module, "global_pipeline_config")

    @global_pipeline_config
    @dataclass(frozen=True)
    class StepConfig(WellFilterConfig):
        step_name: str = "step1"

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Create multiple nested levels
    global_config = GlobalPipelineConfig(num_workers=4)
    path_config = PathPlanningConfig(output_suffix="_custom", well_filter=1)
    step_config = StepConfig(step_name="s1", well_filter=2)

    LazyPathPlanningConfig = LazyDataclassFactory.make_lazy_simple(PathPlanningConfig)
    LazyStepConfig = LazyDataclassFactory.make_lazy_simple(StepConfig)

    # Nested contexts should resolve correctly
    with config_context(global_config):
        with config_context(path_config):
            lazy_path = LazyPathPlanningConfig()
            assert lazy_path.output_suffix == "_custom"
            assert lazy_path.well_filter == 1

        with config_context(step_config):
            lazy_step = LazyStepConfig()
            assert lazy_step.step_name == "s1"
            assert lazy_step.well_filter == 2


def test_lazy_resolution_with_none_fields():
    """Test that None fields in nested configs resolve properly."""

    @dataclass(frozen=True)
    class OptionalFieldConfig:
        required_field: str = "required"
        optional_field: Optional[int] = None

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config
    @dataclass(frozen=True)
    class NestedOptionalConfig(OptionalFieldConfig):
        nested_field: str = "nested"

    _inject_all_pending_fields()

    config = NestedOptionalConfig()
    assert config.required_field == "required"
    assert config.optional_field is None
    assert config.nested_field == "nested"


def test_lazy_inheritance_chain():
    """Test lazy resolution through inheritance chain."""

    @dataclass(frozen=True)
    class Level1Config:
        level1_field: str = "l1"

    @dataclass(frozen=True)
    class Level2Config(Level1Config):
        level2_field: str = "l2"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        global_field: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config
    @dataclass(frozen=True)
    class Level3Config(Level2Config):
        level3_field: str = "l3"

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    global_obj = GlobalConfig()
    l3_obj = Level3Config(level1_field="L1", level2_field="L2", level3_field="L3")

    LazyLevel3Config = LazyDataclassFactory.make_lazy_simple(Level3Config)

    with config_context(global_obj):
        with config_context(l3_obj):
            lazy = LazyLevel3Config()
            assert lazy.level1_field == "L1"
            assert lazy.level2_field == "L2"
            assert lazy.level3_field == "L3"


def test_lazy_with_optional_nested_field():
    """Test lazy resolution when nested field is Optional."""

    @dataclass(frozen=True)
    class OptionalNestedConfig:
        nested_value: str = "nested"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        global_value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(optional=True)
    @dataclass(frozen=True)
    class ParentConfig:
        optional_nested: Optional[OptionalNestedConfig] = None
        parent_value: str = "parent"

    _inject_all_pending_fields()

    parent = ParentConfig()
    assert parent.optional_nested is None
    assert parent.parent_value == "parent"


def test_nested_config_with_inherit_as_none():
    """Test nested configs with inherit_as_none parameter."""

    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1

    module = sys.modules[GlobalConfig.__module__]
    global_config = getattr(module, "global_config")

    @global_config(inherit_as_none=True)
    @dataclass(frozen=True)
    class NestedConfigWithInherit(BaseConfig):
        nested_field: str = "nested"

    _inject_all_pending_fields()

    # Inherited field should be None
    config = NestedConfigWithInherit()
    assert config.base_field is None
    assert config.nested_field == "nested"
