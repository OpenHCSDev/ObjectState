"""Integration tests for the decorator-driven workflow (auto_create_decorator).

These tests mirror the real-world pattern used by OpenHCS and similar consumers:
- Use ``@auto_create_decorator`` on a ``Global*`` dataclass
- Decorate component dataclasses with the generated module-level decorator
- Call ``_inject_all_pending_fields()`` to finalize injection
- Call ``set_base_config_type()`` and use exported ``Lazy...`` classes with ``config_context()``
"""
from dataclasses import dataclass

from hieraconf import auto_create_decorator, config_context, set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_decorator_flow_creates_lazy_and_injection():
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalAppConfig:
        # base field(s)
        global_value: int = 1

    # Define component config and apply the generated decorator at runtime
    @dataclass(frozen=True)
    class ComponentConfig:
        comp_value: int | None = None

    decorator = globals().get("global_app_config")
    assert decorator is not None, "Expected module-level decorator 'global_app_config' to be present"
    decorator(ComponentConfig)

    # Finalize injection (module-level call in real modules)
    _inject_all_pending_fields()

    # Rebind to the possibly-updated GlobalAppConfig class object and register it
    GlobalAppConfig = globals()["GlobalAppConfig"]
    set_base_config_type(GlobalAppConfig)

    # Lazy class should have been exported into this module as LazyComponentConfig
    LazyComponentConfig = globals().get("LazyComponentConfig")
    assert LazyComponentConfig is not None, "LazyComponentConfig not exported by decorator flow"

    # Create a global config instance with a concrete ComponentConfig override
    component_override = ComponentConfig(comp_value=99)
    merged = GlobalAppConfig(component_config=component_override)

    with config_context(merged):
        lazy = LazyComponentConfig()
        assert lazy.comp_value == 99


def test_decorator_flow_generates_lazy_and_injects_fields():
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        output_dir: str = "/tmp"
        num_workers: int = 4

    # Generated decorator will be exported to this module as `global_config`
    decorator = globals().get("global_config")
    assert decorator is not None, "Expected generated decorator 'global_config' to be exported into module globals"

    class _PlainStepConfig:
        step_name: str = "step"
        num_workers: int | None = None

    # Apply dataclass first (bottom decorator) then generated decorator on the dataclass result
    StepConfig = decorator(dataclass(frozen=True)(_PlainStepConfig))

    # We haven't injected fields into GlobalConfig in this test; we only assert lazy class creation
    set_base_config_type(GlobalConfig)

    LazyStepConfig = globals().get("LazyStepConfig")
    assert LazyStepConfig is not None, "LazyStepConfig was not exported into module globals"

    # Use nested contexts: global -> step
    global_cfg = GlobalConfig(output_dir="/data", num_workers=8)
    step_cfg = StepConfig(step_name="s1", num_workers=2)

    with config_context(global_cfg):
        with config_context(step_cfg):
            lazy = LazyStepConfig()
            assert lazy.step_name == "s1"
            assert lazy.num_workers == 2
"""Integration test for the decorator-driven workflow (auto_create_decorator).

This mirrors the real-world pattern used by OpenHCS examples:
1. Use @auto_create_decorator on a Global* dataclass
2. Decorate component dataclasses with the generated decorator
3. Call _inject_all_pending_fields() at module end
4. Call set_base_config_type() and use config_context() with exported Lazy... classes
"""
from dataclasses import dataclass

from hieraconf import auto_create_decorator, config_context, set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_decorator_flow_creates_lazy_and_injection():
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalAppConfig:
        # base field(s)
        global_value: int = 1

    # The module-level decorator `global_app_config` is now available in this module
    @dataclass(frozen=True)
    class ComponentConfig:
        comp_value: int | None = None

    # Apply the generated decorator explicitly (avoids relying on decorator name at parse time)
    decorator = globals().get("global_app_config")
    assert decorator is not None, "Expected module-level decorator 'global_app_config' to be present"
    decorator(ComponentConfig)

    # Finalize injection (module-level call in real modules)
    _inject_all_pending_fields()

    # Register the finalized global config type
    set_base_config_type(GlobalAppConfig)

    # Lazy class should have been exported into this module as LazyComponentConfig
    try:
        LazyComponentConfig = globals()["LazyComponentConfig"]
    except KeyError:
        raise AssertionError("LazyComponentConfig not exported by decorator flow")

    # Create a global config instance with a concrete ComponentConfig override
    component_override = ComponentConfig(comp_value=99)

    # Re-bind to the possibly-updated GlobalAppConfig class object (injection replaces the class in module globals)
    GlobalAppConfig = globals()["GlobalAppConfig"]

    # Construct a global config instance that contains the injected field
    merged = GlobalAppConfig(component_config=component_override)

    with config_context(merged):
        lazy = LazyComponentConfig()
        assert lazy.comp_value == 99
"""Integration test that demonstrates the decorator-driven workflow.

This mirrors the real-world pattern used by OpenHCS: use ``@auto_create_decorator`` on
a `Global*` dataclass, decorate component configs with the generated decorator,
call ``_inject_all_pending_fields()`` to finalize injection, then call
``set_base_config_type()`` and exercise lazy resolution.
"""
from dataclasses import dataclass

from hieraconf import auto_create_decorator, config_context, set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


def test_decorator_flow_generates_lazy_and_injects_fields():
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        output_dir: str = "/tmp"
        num_workers: int = 4

    # Generated decorator will be exported to this module as `global_config`
    # To mimic the common usage order (@global_config above @dataclass) we:
    # 1. create a plain class
    # 2. apply the generated decorator to it (this mutates/marks the class for injection)
    # 3. then apply @dataclass to the returned class
    decorator = globals().get("global_config")
    assert decorator is not None, "Expected generated decorator 'global_config' to be exported into module globals"

    class _PlainStepConfig:
        step_name: str = "step"
        num_workers: int | None = None

    # Apply dataclass first (bottom decorator) then generated decorator on the
    # dataclass result; this mirrors using ``@global_config`` above ``@dataclass``
    StepConfig = decorator(dataclass(frozen=True)(_PlainStepConfig))

    # NOTE: In real applications you will often call _inject_all_pending_fields()
    # to inject component fields into the Global* dataclass. For this test we
    # demonstrate the decorator-driven generation of lazy classes and nested
    # context resolution (without module-level injection).

    # Register base config type
    set_base_config_type(GlobalConfig)

    # The lazy class should have been exported into this module as `LazyStepConfig`
    LazyStepConfig = globals().get("LazyStepConfig")
    assert LazyStepConfig is not None, "LazyStepConfig was not exported into module globals"

    # Use nested contexts: global -> step
    global_cfg = GlobalConfig(output_dir="/data", num_workers=8)
    step_cfg = StepConfig(step_name="s1", num_workers=2)

    with config_context(global_cfg):
        with config_context(step_cfg):
            lazy = LazyStepConfig()
            assert lazy.step_name == "s1"
            assert lazy.num_workers == 2
