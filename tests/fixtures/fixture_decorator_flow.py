"""Fixture module: decorator + injection flow at import time.

This module defines a Global* dataclass and component dataclasses at module
scope, applies the generated decorator to the components, finalizes
injection, and registers the base config type. Tests can import this module
to observe the real import-time behavior.
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
