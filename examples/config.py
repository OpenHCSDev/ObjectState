"""Trimmed example demonstrating decorator-driven workflow with mixins.

This example is dependency-free and shows:
- `@auto_create_decorator` on a `Global*` dataclass
- mixin-style reuse via `WellFilterConfig` and `PathPlanningConfig`
- `inherit_as_none` usage for inherited defaults
- finalization via `_inject_all_pending_fields()` and `set_base_config_type()`

Import this module in tests to observe module-level decoration/injection behavior.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from hieraconf import auto_create_decorator, set_base_config_type
from hieraconf.lazy_factory import _inject_all_pending_fields


class WellFilterMode(Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class Compression(Enum):
    NONE = "none"
    ZLIB = "zlib"


@auto_create_decorator
@dataclass(frozen=True)
class GlobalPipelineConfig:
    """Root (global) configuration for a pipeline session."""

    num_workers: int = 2
    materialization_path: Path = field(default=Path("results"))


@dataclass(frozen=True)
class WellFilterConfig:
    """Mixin-like config providing well filtering options."""

    well_filter: list[str] | None = None
    well_filter_mode: WellFilterMode = WellFilterMode.INCLUDE


@dataclass(frozen=True)
class ZarrConfig:
    compressor: Compression = Compression.ZLIB
    compression_level: int = 3


@dataclass(frozen=True)
class PathPlanningConfig(WellFilterConfig):
    """Config that inherits well-filtering behavior from WellFilterConfig."""

    output_dir: Path = field(default=Path("/data"))
    sub_dir: str = "pipeline"


# Small base class that provides defaults which we may want to 'inherit as None'
class BaseDefaults:
    timeout: int = 30


@dataclass(frozen=True)
class ComponentConfig(BaseDefaults):
    """A component config that inherits defaults from BaseDefaults."""

    comp_value: int | None = None


@dataclass(frozen=True)
class StorageConfig:
    enable_cache: bool = False
    chunk_size: int = 256


# Apply the generated decorator to component configs. Demonstrate inherit_as_none
# flag for ComponentConfig so inherited defaults become None before dataclass runs.
decorator = globals().get("global_pipeline_config")
if decorator is not None:
    decorator(ComponentConfig, inherit_as_none=True)
    decorator(StorageConfig)


# Finalize injection at module import time
_inject_all_pending_fields()


# Register the finalized base global type
set_base_config_type(GlobalPipelineConfig)
