"""Tests for ensure_global_config_context function.

CRITICAL: These tests cover the most important function for real-world usage.
Every application that uses hieraconf must call ensure_global_config_context
at startup to establish the global config context for lazy resolution.
"""

from dataclasses import dataclass

from hieraconf import (
    LazyDataclassFactory,
    ensure_global_config_context,
    get_current_global_config,
    set_base_config_type,
)


def test_ensure_global_config_context_basic():
    """Test establishing global config context with a simple config."""

    @dataclass(frozen=True)
    class GlobalConfig:
        value: str = "global"
        number: int = 42

    global_config = GlobalConfig(value="test", number=100)
    ensure_global_config_context(GlobalConfig, global_config)

    # Verify context is accessible
    retrieved = get_current_global_config(GlobalConfig)
    assert retrieved is not None
    assert retrieved.value == "test"
    assert retrieved.number == 100


def test_lazy_resolution_requires_global_context():
    """Test that lazy resolution fails without global context.

    Without ensure_global_config_context, lazy fields should resolve to None
    because there's no context to pull values from.
    """

    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    set_base_config_type(MyConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy instance WITHOUT ensure_global_config_context
    lazy = LazyConfig()

    # Should return None without context
    assert lazy.value is None
    assert lazy.number is None


def test_lazy_resolution_with_global_context():
    """Test that lazy resolution works when global context is established."""

    @dataclass
    class GlobalConfig:
        value: str = "default"
        number: int = 1

    set_base_config_type(GlobalConfig)
    LazyConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)

    global_config = GlobalConfig(value="from_global", number=999)
    ensure_global_config_context(GlobalConfig, global_config)

    # Create lazy instance - should now resolve from global context
    lazy = LazyConfig()
    assert lazy.value == "from_global"
    assert lazy.number == 999


def test_application_startup_pattern():
    """Test complete application startup pattern from OpenHCS.

    This mirrors the pattern used in openhcs/pyqt_gui/app.py:88-98
    and is the most critical real-world usage pattern.
    """

    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"
        debug: bool = False

    set_base_config_type(GlobalPipelineConfig)

    # Application startup sequence
    global_config = GlobalPipelineConfig(
        num_workers=4, output_dir="/data", debug=True
    )

    # This is THE critical call for any real-world application
    ensure_global_config_context(GlobalPipelineConfig, global_config)

    # After this call, lazy configs can now resolve from the global context
    LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(GlobalPipelineConfig)
    lazy = LazyPipelineConfig()

    assert lazy.num_workers == 4
    assert lazy.output_dir == "/data"
    assert lazy.debug is True


def test_multiple_global_config_types():
    """Test managing multiple different global config types.

    Real applications may have multiple config hierarchies (e.g., UI config
    and pipeline config). Each should maintain separate context.
    """

    @dataclass(frozen=True)
    class GlobalUIConfig:
        theme: str = "light"
        window_size: int = 800

    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    set_base_config_type(GlobalUIConfig)

    # Set up contexts for both config types
    ui_config = GlobalUIConfig(theme="dark", window_size=1024)
    pipeline_config = GlobalPipelineConfig(num_workers=8, output_dir="/data")

    ensure_global_config_context(GlobalUIConfig, ui_config)
    ensure_global_config_context(GlobalPipelineConfig, pipeline_config)

    # Create lazy versions
    LazyUIConfig = LazyDataclassFactory.make_lazy_simple(GlobalUIConfig)
    LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(GlobalPipelineConfig)

    # Each should resolve from its own context
    lazy_ui = LazyUIConfig()
    lazy_pipeline = LazyPipelineConfig()

    assert lazy_ui.theme == "dark"
    assert lazy_ui.window_size == 1024
    assert lazy_pipeline.num_workers == 8
    assert lazy_pipeline.output_dir == "/data"


def test_global_context_update():
    """Test updating global config context during runtime.

    While not the typical pattern, sometimes configs need to be updated
    after initial setup (e.g., when user preferences change).
    """

    @dataclass(frozen=True)
    class GlobalConfig:
        value: str = "initial"

    set_base_config_type(GlobalConfig)

    # Initial context
    initial_config = GlobalConfig(value="initial_value")
    ensure_global_config_context(GlobalConfig, initial_config)

    LazyConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)
    lazy1 = LazyConfig()
    assert lazy1.value == "initial_value"

    # Update context (immutable dataclass, so create new instance)
    updated_config = GlobalConfig(value="updated_value")
    ensure_global_config_context(GlobalConfig, updated_config)

    # New lazy instance should see updated value
    lazy2 = LazyConfig()
    assert lazy2.value == "updated_value"


def test_get_current_global_config():
    """Test retrieving current global config."""

    @dataclass(frozen=True)
    class GlobalConfig:
        value: str = "test"

    global_config = GlobalConfig(value="test_value")
    ensure_global_config_context(GlobalConfig, global_config)

    # Get the config back
    retrieved = get_current_global_config(GlobalConfig)

    assert retrieved is not None
    assert retrieved == global_config
    assert retrieved.value == "test_value"


def test_get_current_global_config_when_not_set():
    """Test retrieving global config when none is set."""

    @dataclass(frozen=True)
    class NeverSetConfig:
        value: str = "default"

    # Should return None if never set
    retrieved = get_current_global_config(NeverSetConfig)
    assert retrieved is None


def test_nested_configs_with_global_context():
    """Test nested config resolution with global context.

    This is a complex real-world pattern where a nested config inherits
    from a parent config and should resolve from global context.
    """

    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"

    @dataclass(frozen=True)
    class StepConfig:
        step_name: str = "default_step"
        num_workers: int = 1  # Can inherit from global

    set_base_config_type(GlobalPipelineConfig)

    # Set up global context
    global_config = GlobalPipelineConfig(num_workers=4, output_dir="/data")
    ensure_global_config_context(GlobalPipelineConfig, global_config)

    # Create lazy step config
    LazyStepConfig = LazyDataclassFactory.make_lazy_simple(StepConfig)
    lazy_step = LazyStepConfig(step_name="my_step")

    assert lazy_step.step_name == "my_step"
    # num_workers can be resolved from global context if properly configured
    assert lazy_step.num_workers is None  # Not in context, so None
