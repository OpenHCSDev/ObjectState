# lazy-config

**Generic lazy dataclass configuration framework with dual-axis inheritance**

[![PyPI version](https://badge.fury.io/py/lazy-config.svg)](https://badge.fury.io/py/lazy-config)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Lazy Dataclass Factory**: Dynamically create dataclasses with lazy field resolution
- **Dual-Axis Inheritance**: 
  - X-Axis: Context hierarchy (Step → Pipeline → Global)
  - Y-Axis: Sibling inheritance within same context
- **Contextvars-Based**: Uses Python's `contextvars` for clean context management
- **UI Integration**: Placeholder text generation for configuration forms
- **Thread-Safe**: Thread-local global configuration storage
- **100% Generic**: No application-specific dependencies
- **Pure Stdlib**: No external dependencies

## Quick Start

### Simple Usage (Manual Factory)

```python
from dataclasses import dataclass
from lazy_config import LazyDataclassFactory, config_context, set_base_config_type

# Define your base configuration
@dataclass
class MyConfig:
    output_dir: str = "/tmp"
    num_workers: int = 4
    debug: bool = False

# Initialize the framework with your base config type
set_base_config_type(MyConfig)

# Create lazy version manually
LazyMyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

# Use with context
concrete_config = MyConfig(output_dir="/data", num_workers=8)

with config_context(concrete_config):
    lazy_cfg = LazyMyConfig()
    print(lazy_cfg.output_dir)  # "/data" (resolved from context)
    print(lazy_cfg.num_workers)  # 8 (resolved from context)
    print(lazy_cfg.debug)        # False (inherited from defaults)
```

## Installation

```bash
pip install lazy-config
```

## Automatic Lazy Config Generation with Decorators

For more complex applications with multiple config types, use the `auto_create_decorator` pattern to automatically generate lazy versions and field injection decorators:

```python
from dataclasses import dataclass
from lazy_config import auto_create_decorator, config_context

# Step 1: Create a global config class with "Global" prefix and apply auto_create_decorator
@auto_create_decorator
@dataclass
class GlobalPipelineConfig:
    base_output_dir: str = "/tmp"
    verbose: bool = False

# This automatically creates:
# - A decorator named `global_pipeline_config` (snake_case of class name)
#   that you can use to decorate other config classes
# - A lazy class `PipelineConfig` (removes "Global" prefix) for lazy resolution

# Step 2: Use the generated decorator on other config classes
@global_pipeline_config  # Automatically creates LazyStepConfig
@dataclass
class StepConfig:
    step_name: str = "default_step"
    iterations: int = 100

@global_pipeline_config  # Automatically creates LazyDatabaseConfig  
@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432

# The decorator automatically:
# - Creates lazy versions: LazyStepConfig, LazyDatabaseConfig
# - Registers them for potential field injection into GlobalPipelineConfig
# - Makes them available in your module namespace
```

**Key Benefits:**
- **Auto-generated lazy classes**: Each decorated config automatically gets a lazy version
- **Simplified imports**: Lazy classes are automatically added to your module
- **Decorator factory**: `auto_create_decorator` generates a decorator specific to your global config
- **Type-safe**: All generated classes are proper dataclasses with full IDE support

## Why lazy-config?

**Before** (Manual parameter passing):
```python
def process_step(data, output_dir, num_workers, debug, ...):
    # Pass 20+ parameters through every function
    result = sub_process(data, output_dir, num_workers, debug, ...)
    return result

def sub_process(data, output_dir, num_workers, debug, ...):
    # Repeat parameter declarations everywhere
    ...
```

**After** (lazy-config):
```python
@dataclass
class StepConfig:
    output_dir: str = None
    num_workers: int = None
    debug: bool = None

def process_step(data, config: LazyStepConfig):
    # Config fields resolve automatically from context
    print(config.output_dir)  # Resolved from context hierarchy
    result = sub_process(data, config)
    return result
```

## Advanced Features

### Dual-Axis Inheritance

```python
# X-Axis: Context hierarchy
with config_context(global_config):
    with config_context(pipeline_config):
        with config_context(step_config):
            # Resolves: step → pipeline → global → defaults
            value = lazy_config.some_field

# Y-Axis: Sibling inheritance (MRO-based)
@dataclass
class BaseConfig:
    field_a: str = "base"

@dataclass
class SpecializedConfig(BaseConfig):
    field_b: str = "specialized"

# SpecializedConfig inherits field_a from BaseConfig
```

### Placeholder Generation for UI

```python
from lazy_config import LazyDefaultPlaceholderService

service = LazyDefaultPlaceholderService()

# Generate placeholder text showing inherited values
placeholder = service.get_placeholder_text(
    lazy_config,
    "output_dir",
    available_configs
)
# Returns: "Inherited: /data (from GlobalConfig)"
```

### Cache Warming

```python
from lazy_config import prewarm_config_analysis_cache

# Pre-warm caches for faster runtime resolution
prewarm_config_analysis_cache([GlobalConfig, PipelineConfig, StepConfig])
```

## Architecture

### Dual-Axis Resolution

The framework uses pure MRO-based dual-axis resolution:

**X-Axis (Context Hierarchy)**:
```
Step Context → Pipeline Context → Global Context → Static Defaults
```

**Y-Axis (MRO Traversal)**:
```
Most specific class → Least specific class (following Python's MRO)
```

**How it works:**
1. Context hierarchy is flattened into a single `available_configs` dict
2. For each field resolution, traverse the requesting object's MRO from most to least specific
3. For each MRO class, check if there's a config instance in `available_configs` with a concrete (non-None) value
4. Return the first concrete value found

## Documentation

Full documentation available at [lazy-config.readthedocs.io](https://lazy-config.readthedocs.io)

## Requirements

- Python 3.10+
- No external dependencies (pure stdlib)

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

## Credits

Developed by Tristan Simas as part of the OpenHCS project.
