"""Small fixture module that demonstrates the decorator-driven workflow.

This is intentionally minimal and dependency-free so tests can import it
and observe the decorator + injection behavior as it occurs at module import time.
"""
from dataclasses import dataclass

from hieraconf import auto_create_decorator
from hieraconf import set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


@auto_create_decorator
@dataclass(frozen=True)
class GlobalTestConfig:
    # Base/global fields
    global_value: int = 0


@dataclass(frozen=True)
class ComponentConfig:
    comp_value: int | None = None


@dataclass(frozen=True)
class OtherConfig:
    other_flag: bool = False


# Apply the generated decorator explicitly to avoid any name-resolution timing issues
decorator = globals().get("global_test_config")
if decorator is None:
    # Fallback: try importing from hieraconf.lazy_factory (shouldn't be necessary in normal import)
    from hieraconf import auto_create_decorator as _tmp_deco
    decorator = globals().get("global_test_config")

if decorator is not None:
    decorator(ComponentConfig)
    decorator(OtherConfig)


# Finalize pending injections at module import time (mirrors real app modules)
_inject_all_pending_fields()

# Register the finalized global config type for the framework
set_base_config_type(GlobalTestConfig)
