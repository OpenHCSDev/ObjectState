"""Clean fixture: generate a StepConfig via decorator(dataclass(...)) pattern.

This mirrors using the generated decorator above @dataclass: create a plain
class, apply @dataclass to it, then pass that to the generated decorator. The
module exports the resulting LazyStepConfig for tests to import and inspect.
"""

decorator = globals().get("global_step_config")
from dataclasses import dataclass

from hieraconf import auto_create_decorator, set_base_config_type
from hieraconf.lazy_factory import LazyDataclassFactory


@auto_create_decorator
@dataclass(frozen=True)
class GlobalStepConfig:
    output_dir: str = "/tmp"


class StepConfig:
    step_name: str = "step"
    num_workers: int | None = None


# Get generated decorator and apply to dataclass result
decorator = globals().get("global_step_config")
if decorator is not None:
    # Apply decorator to a dataclass named 'StepConfig' so generated lazy class is
    # exported as 'LazyStepConfig' (matching common expectations)
    StepConfig = decorator(dataclass(frozen=True)(StepConfig))
    # Ensure a LazyStepConfig is exported into this module (some environments
    # may not export immediately). Create fallback lazy class if missing.
    lazy_name = f"Lazy{StepConfig.__name__}"
    if lazy_name not in globals():
        LazyStepConfig = LazyDataclassFactory.make_lazy_simple(
            base_class=StepConfig, lazy_class_name=lazy_name
        )
        globals()[lazy_name] = LazyStepConfig

    # Register the base global config type for resolution
    set_base_config_type(GlobalStepConfig)
