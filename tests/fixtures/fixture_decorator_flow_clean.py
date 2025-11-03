"""Clean fixture module: decorator + injection flow at import time.

Defines a Global* dataclass and a component dataclass at module scope. It
applies the generated decorator to the component, finalizes injection, and
registers the base config type. Tests import this module to observe the
real import-time behavior without editing the original fixture files.
"""

from dataclasses import dataclass

from hieraconf import auto_create_decorator, set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


@auto_create_decorator
@dataclass(frozen=True)
class GlobalGenConfig:
    foo: int = 0


@dataclass(frozen=True)
class ComponentConfig:
    comp_value: int | None = None


# Apply decorator and finalize injection at import time
decorator = globals().get("global_gen_config")
if decorator is not None:
    decorator(ComponentConfig)

_inject_all_pending_fields()
set_base_config_type(GlobalGenConfig)
