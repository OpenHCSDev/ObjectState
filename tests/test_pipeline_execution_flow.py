"""Integration tests for complete pipeline execution flow.

Tests the real-world pattern from OpenHCS where configs are used with
nested contexts (Global → Pipeline → Step) and lazy resolution through
the entire hierarchy.
"""

from dataclasses import dataclass
from typing import Optional

from hieraconf import (
    LazyDataclassFactory,
    auto_create_decorator,
    config_context,
    ensure_global_config_context,
    set_base_config_type,
)
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_complete_pipeline_flow():
    """Test complete pipeline execution flow with nested contexts.

    This mimics the pattern from OpenHCS where:
    1. Global config is set up at startup
    2. Pipeline config wraps the global config
    3. Step configs refine the pipeline config
    4. Lazy resolution works at each level
    """

    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None
        well_filter_mode: str = "include"

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    module_globals = {}
    # Simulate finding decorator in module
    import sys
    module = sys.modules[__name__]
    global_pipeline_config_decorator = getattr(module, "global_pipeline_config", None)
    if global_pipeline_config_decorator is None:
        # For testing, we need to access the decorator
        from hieraconf.lazy_factory import create_global_default_decorator
        global_pipeline_config_decorator = create_global_default_decorator(
            GlobalPipelineConfig
        )

    # Define pipeline config
    @global_pipeline_config_decorator
    @dataclass(frozen=True)
    class PipelineConfig(WellFilterConfig):
        output_dir_suffix: str = "_openhcs"

    # Define step configs
    @global_pipeline_config_decorator
    @dataclass(frozen=True)
    class StepConfig(WellFilterConfig):
        step_name: str = "default"
        step_specific_value: int = 1

    _inject_all_pending_fields()
    set_base_config_type(GlobalPipelineConfig)

    # Simulate application startup
    global_config = GlobalPipelineConfig(num_workers=4, output_dir="/data")
    ensure_global_config_context(GlobalPipelineConfig, global_config)

    # Create lazy versions for each level
    LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(PipelineConfig)
    LazyStepConfig = LazyDataclassFactory.make_lazy_simple(StepConfig)

    # Create concrete instances for each level
    pipeline_config = PipelineConfig(
        output_dir_suffix="_custom", well_filter=1, well_filter_mode="exclude"
    )
    step1_config = StepConfig(step_name="step1", well_filter=2)
    step2_config = StepConfig(step_name="step2", well_filter=3)

    # Test pipeline-level resolution
    with config_context(global_config):
        with config_context(pipeline_config):
            lazy_pipeline = LazyPipelineConfig()
            assert lazy_pipeline.num_workers == 4  # From global
            assert lazy_pipeline.output_dir == "/data"  # From global
            assert lazy_pipeline.output_dir_suffix == "_custom"  # From pipeline
            assert lazy_pipeline.well_filter == 1  # From pipeline
            assert lazy_pipeline.well_filter_mode == "exclude"  # From pipeline

    # Test step1-level resolution
    with config_context(global_config):
        with config_context(pipeline_config):
            with config_context(step1_config):
                lazy_step1 = LazyStepConfig()
                assert lazy_step1.step_name == "step1"  # From step
                assert lazy_step1.well_filter == 2  # From step (overrides pipeline)
                assert lazy_step1.step_specific_value == 1  # From step defaults

    # Test step2-level resolution
    with config_context(global_config):
        with config_context(pipeline_config):
            with config_context(step2_config):
                lazy_step2 = LazyStepConfig()
                assert lazy_step2.step_name == "step2"  # From step
                assert lazy_step2.well_filter == 3  # From step (different from step1)


def test_multiple_pipelines_in_sequence():
    """Test using different pipeline configs in sequence."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        setting: str = "default"

    import sys
    from hieraconf.lazy_factory import create_global_default_decorator

    module = sys.modules[__name__]
    global_config_decorator = create_global_default_decorator(GlobalConfig)

    @global_config_decorator
    @dataclass(frozen=True)
    class Pipeline1Config:
        pipeline_id: str = "p1"

    @global_config_decorator
    @dataclass(frozen=True)
    class Pipeline2Config:
        pipeline_id: str = "p2"

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    global_config = GlobalConfig(setting="prod")
    ensure_global_config_context(GlobalConfig, global_config)

    LazyPipeline1 = LazyDataclassFactory.make_lazy_simple(Pipeline1Config)
    LazyPipeline2 = LazyDataclassFactory.make_lazy_simple(Pipeline2Config)

    p1_config = Pipeline1Config(pipeline_id="pipeline_one")
    p2_config = Pipeline2Config(pipeline_id="pipeline_two")

    # Run pipeline 1
    with config_context(global_config):
        with config_context(p1_config):
            lazy1 = LazyPipeline1()
            assert lazy1.pipeline_id == "pipeline_one"

    # Run pipeline 2
    with config_context(global_config):
        with config_context(p2_config):
            lazy2 = LazyPipeline2()
            assert lazy2.pipeline_id == "pipeline_two"


def test_pipeline_with_optional_configs():
    """Test pipeline that may skip optional configs."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        num_workers: int = 1

    import sys
    from hieraconf.lazy_factory import create_global_default_decorator

    global_config_decorator = create_global_default_decorator(GlobalConfig)

    @global_config_decorator(optional=True)
    @dataclass(frozen=True)
    class OptionalStepConfig:
        optional_setting: str = "optional"

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    global_config = GlobalConfig(num_workers=8)
    ensure_global_config_context(GlobalConfig, global_config)

    # When optional step is not provided, lazy resolution should handle gracefully
    LazyOptionalStep = LazyDataclassFactory.make_lazy_simple(OptionalStepConfig)

    # Without context, should return None
    lazy_no_context = LazyOptionalStep()
    assert lazy_no_context.optional_setting is None

    # With context, should resolve
    optional_step = OptionalStepConfig(optional_setting="custom")
    with config_context(global_config):
        with config_context(optional_step):
            lazy_with_context = LazyOptionalStep()
            assert lazy_with_context.optional_setting == "custom"


def test_placeholder_resolution_in_nested_contexts():
    """Test placeholder text generation in nested contexts.

    This simulates UI layer behavior where it needs placeholder text
    for each field at each context level.
    """
    from hieraconf import LazyDefaultPlaceholderService

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        output_dir: str = "/data"
        num_workers: int = 4

    import sys
    from hieraconf.lazy_factory import create_global_default_decorator

    global_config_decorator = create_global_default_decorator(GlobalConfig)

    @global_config_decorator
    @dataclass(frozen=True)
    class PipelineConfig:
        output_suffix: str = "_plan"
        workers_override: Optional[int] = None

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    # Create placeholder service
    service = LazyDefaultPlaceholderService()

    global_config = GlobalConfig(output_dir="/custom", num_workers=8)
    pipeline_config = PipelineConfig(output_suffix="_my_plan")

    # Get placeholder for global config
    with config_context(global_config):
        placeholder_output_dir = service.get_lazy_resolved_placeholder(
            GlobalConfig, "output_dir"
        )
        assert placeholder_output_dir is not None  # Should have default value

    # Get placeholder for pipeline config
    with config_context(global_config):
        with config_context(pipeline_config):
            placeholder_suffix = service.get_lazy_resolved_placeholder(
                PipelineConfig, "output_suffix"
            )
            assert placeholder_suffix is not None  # Should have value from context


def test_config_context_stacking_order():
    """Test that context stack is respected in correct order."""

    @dataclass(frozen=True)
    class Config1:
        value: str = "default"

    @dataclass(frozen=True)
    class Config2(Config1):
        extra: int = 0

    set_base_config_type(Config1)

    LazyConfig2 = LazyDataclassFactory.make_lazy_simple(Config2)

    c1 = Config1(value="from_c1")
    c2 = Config2(value="from_c2", extra=99)

    # Config2 is more specific, should be used
    with config_context(c1):
        with config_context(c2):
            lazy = LazyConfig2()
            assert lazy.value == "from_c2"
            assert lazy.extra == 99

    # When only c1 is in context, should resolve from it
    with config_context(c1):
        lazy = LazyConfig2()
        # extra not in c1, so should be None
        assert lazy.extra is None or lazy.extra == 0


def test_ensure_global_context_enables_standalone_lazy_resolution():
    """Test that ensure_global_config_context enables lazy resolution without explicit context."""

    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        app_name: str = "myapp"
        debug: bool = False

    import sys
    from hieraconf.lazy_factory import create_global_default_decorator

    global_config_decorator = create_global_default_decorator(GlobalConfig)

    @global_config_decorator
    @dataclass(frozen=True)
    class AppConfig(GlobalConfig):
        port: int = 8080

    _inject_all_pending_fields()
    set_base_config_type(GlobalConfig)

    # Set up global context at startup
    global_config = GlobalConfig(app_name="production_app", debug=True)
    ensure_global_config_context(GlobalConfig, global_config)

    LazyAppConfig = LazyDataclassFactory.make_lazy_simple(AppConfig)

    # Can now create lazy config without explicit context
    lazy_app = LazyAppConfig()

    # Should resolve from global context
    assert lazy_app.app_name == "production_app"
    assert lazy_app.debug is True
    assert lazy_app.port is None or lazy_app.port == 8080
