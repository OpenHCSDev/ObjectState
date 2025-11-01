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

### Setting Up Global Config Context (For Advanced Usage)

When using the decorator pattern with `auto_create_decorator`, you need to establish the global configuration context for lazy resolution:

```python
from lazy_config import ensure_global_config_context

# After creating your global config instance
global_config = GlobalPipelineConfig(
    num_workers=8,
    # ... other fields
)

# REQUIRED: Establish global config context for lazy resolution
ensure_global_config_context(GlobalPipelineConfig, global_config)

# Now lazy configs can resolve from the global context
```

**Key differences:**
- `set_base_config_type(MyConfig)`: Sets the **type** (class) for the framework
- `ensure_global_config_context(GlobalConfig, instance)`: Sets the **instance** (concrete values) for resolution
- Call `ensure_global_config_context()` at application startup (GUI) or before pipeline execution

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

### Field Injection Behavior

When you use the generated decorator (e.g., `@global_pipeline_config`), the decorated class is automatically **injected as a field** into the global config class:

```python
from dataclasses import dataclass
from lazy_config import auto_create_decorator

# Create global config with auto_create_decorator
@auto_create_decorator
@dataclass
class GlobalPipelineConfig:
    num_workers: int = 1

# This creates:
# - A decorator named `global_pipeline_config`
# - A lazy class named `PipelineConfig`

# Use the decorator on a new config class
@global_pipeline_config
@dataclass
class WellFilterConfig:
    well_filter: str = None
    mode: str = "include"

# After module loading, GlobalPipelineConfig automatically has:
# - well_filter_config: WellFilterConfig = WellFilterConfig()
# And LazyWellFilterConfig is auto-created
```

**How it works:**
- Decorated classes are injected as fields into `GlobalPipelineConfig`
- Field name is snake_case of class name (e.g., `WellFilterConfig` → `well_filter_config`)
- Lazy version is automatically created (e.g., `LazyWellFilterConfig`)
- Injection happens at end of module loading via `_inject_all_pending_fields()`

This enables a clean, modular configuration structure where each component's config is automatically part of the global configuration.

### Decorator Parameters

The generated decorator (e.g., `@global_pipeline_config`) supports optional parameters:

#### `inherit_as_none` (Default: `True`)

Sets all inherited fields from parent classes to `None` by default, enabling proper lazy resolution:

```python
@dataclass
class BaseConfig:
    timeout: int = 30
    retries: int = 3

@global_pipeline_config(inherit_as_none=True)  # Default behavior
@dataclass
class ServiceConfig(BaseConfig):
    service_name: str = "my-service"
    # timeout and retries automatically set to None for lazy inheritance

# This allows ServiceConfig to inherit timeout/retries from context
# rather than using the base class defaults
```

**Why this matters:**
- Enables polymorphic access without type-specific attribute names
- Critical for dual-axis inheritance with multiple inheritance
- Uses `InheritAsNoneMeta` metaclass internally

#### `ui_hidden` (Default: `False`)

Hides configs from UI while still applying decorator behavior and keeping them in the resolution context:

```python
@global_pipeline_config(ui_hidden=True)
@dataclass
class InternalConfig:
    internal_setting: str = "hidden"
    # This config won't appear in UI but is still available for inheritance
```

**Use cases:**
- Intermediate configs that are only inherited by other configs
- Internal implementation details not meant for user configuration
- Base classes that should never be directly instantiated in UI

### Nested Dataclass Lazification

When creating a lazy dataclass, **nested dataclass fields are automatically converted** to their lazy versions:

```python
from dataclasses import dataclass
from lazy_config import LazyDataclassFactory

@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432

@dataclass
class AppConfig:
    db_config: DatabaseConfig = DatabaseConfig()
    app_name: str = "MyApp"

# Create lazy version - nested configs are automatically lazified
LazyAppConfig = LazyDataclassFactory.make_lazy_simple(AppConfig)

# The db_config field is automatically converted to LazyDatabaseConfig
# You don't need to manually create LazyDatabaseConfig first!
```

**Benefits:**
- No need to manually create lazy versions of nested configs
- Preserves field metadata (e.g., `ui_hidden` flag)
- Creates default factories for Optional dataclass fields
- Uses `register_lazy_type_mapping()` internally

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
