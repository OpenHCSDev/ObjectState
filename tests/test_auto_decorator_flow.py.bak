"""Tests for the decorator-driven workflow using import-time fixtures.

We import small fixture modules that perform the decorator/injection flow at
module import time so the library's side effects (exporting Lazy classes,
injecting fields) occur as they do in real applications.
"""

import importlib
from types import SimpleNamespace

from hieraconf import set_current_temp_global, clear_current_temp_global, config_context


def test_fixture_decorator_flow_exports_lazy_and_resolves():
    fixture = importlib.import_module("tests.fixtures.fixture_decorator_flow_clean")

    LazyComponentConfig = getattr(fixture, "LazyComponentConfig", None)
    assert LazyComponentConfig is not None, "LazyComponentConfig should be exported from fixture_decorator_flow"

    # Simulate merged context object (module-level injection would normally set this up)
    component_override = fixture.ComponentConfig(comp_value=321)
    merged_ctx = SimpleNamespace(component_config=component_override)

    set_current_temp_global(merged_ctx)
    try:
        lazy = LazyComponentConfig()
        assert lazy.comp_value == 321
    finally:
        clear_current_temp_global()


def test_step_decorator_pattern_exports_lazy_and_works_with_nested_contexts():
    fixture = importlib.import_module("tests.fixtures.fixture_step_decorator_clean")

    LazyStepConfig = getattr(fixture, "LazyStepConfig", None)
    assert LazyStepConfig is not None, "LazyStepConfig should be exported from fixture_step_decorator"

    # Create concrete base/global and step configs and use config_context nesting
    GlobalStepConfig = getattr(fixture, "GlobalStepConfig")
    StepConfig = getattr(fixture, "StepConfig")

    global_cfg = GlobalStepConfig(output_dir="/data")
    step_cfg = StepConfig(step_name="s1", num_workers=2)

    with config_context(global_cfg):
        with config_context(step_cfg):
            lazy = LazyStepConfig()
            assert lazy.step_name == "s1"
            assert lazy.num_workers == 2
"""Tests for the decorator-driven workflow using import-time fixtures.
"""Tests for the decorator-driven workflow using import-time fixtures.

We import small fixture modules that perform the decorator/injection flow at
module import time so the library's side effects (exporting Lazy classes,
injecting fields) occur as they do in real applications.
"""

import importlib
from types import SimpleNamespace

from hieraconf import set_current_temp_global, clear_current_temp_global, config_context


def test_fixture_decorator_flow_exports_lazy_and_resolves():
    fixture = importlib.import_module("tests.fixtures.fixture_decorator_flow_clean")

    LazyComponentConfig = getattr(fixture, "LazyComponentConfig", None)
    assert LazyComponentConfig is not None, "LazyComponentConfig should be exported from fixture_decorator_flow"

    # Simulate merged context object (module-level injection would normally set this up)
    component_override = fixture.ComponentConfig(comp_value=321)
    merged_ctx = SimpleNamespace(component_config=component_override)

    set_current_temp_global(merged_ctx)
    try:
        lazy = LazyComponentConfig()
        assert lazy.comp_value == 321
    finally:
        clear_current_temp_global()


def test_step_decorator_pattern_exports_lazy_and_works_with_nested_contexts():
    fixture = importlib.import_module("tests.fixtures.fixture_step_decorator_clean")

    LazyStepConfig = getattr(fixture, "LazyStepConfig", None)
    assert LazyStepConfig is not None, "LazyStepConfig should be exported from fixture_step_decorator"

    # Create concrete base/global and step configs and use config_context nesting
    GlobalStepConfig = getattr(fixture, "GlobalStepConfig")
    StepConfig = getattr(fixture, "StepConfig")

    global_cfg = GlobalStepConfig(output_dir="/data")
    step_cfg = StepConfig(step_name="s1", num_workers=2)

    with config_context(global_cfg):
        with config_context(step_cfg):
            lazy = LazyStepConfig()
            assert lazy.step_name == "s1"
            assert lazy.num_workers == 2
