"""Fixture module: generate a StepConfig via decorator(dataclass(...)) pattern.

This mirrors using the generated decorator above @dataclass: create a plain
class, apply @dataclass to it, then pass that to the generated decorator. The
module exports the resulting LazyStepConfig for tests to import and inspect.
"""

from dataclasses import dataclass

from hieraconf import auto_create_decorator, set_base_config_type


@auto_create_decorator
@dataclass(frozen=True)
class GlobalStepConfig:
    output_dir: str = "/tmp"


class _PlainStepConfig:
    step_name: str = "step"
    num_workers: int | None = None


# Get generated decorator and apply to dataclass result
decorator = globals().get("global_step_config")
if decorator is not None:
    StepConfig = decorator(dataclass(frozen=True)(_PlainStepConfig))
    # We don't need to inject fields into Global in this fixture; just register base
    set_base_config_type(GlobalStepConfig)
