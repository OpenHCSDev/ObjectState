# Lazy-Config Documentation Fixes Plan

**Source of Truth**: OpenHCS `docs/source/architecture/configuration_framework.rst` and actual usage in `openhcs/core/config.py`

**Goal**: Fix inaccuracies in hieraconf documentation and add missing critical features

---

## Critical Issues to Fix

### 1. **INCORRECT: Factory Instantiation Pattern**

**Current (WRONG)**:
```python
factory = LazyDataclassFactory()
LazyMyConfig = factory.make_lazy_simple(MyConfig)
```

**Correct**:
```python
LazyMyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)
```

**Why**: `make_lazy_simple()` is a **static method**, not an instance method. OpenHCS never instantiates the factory.

**Files to fix**:
- `README.md` - Check all code examples
- `docs/index.rst` - Quick example section
- `docs/quickstart.rst` - Create lazy version section
- `docs/examples/basic.rst` - All examples
- `docs/examples/dual_axis.rst` - Check for factory usage

---

## Missing Features to Document

### 2. **Field Injection Behavior**

**What it is**: Classes decorated with `@global_pipeline_config` (or any generated decorator) automatically get their fields injected into the GlobalPipelineConfig class.

**Example from OpenHCS**:
```python
@auto_create_decorator
@dataclass(frozen=True)
class GlobalPipelineConfig:
    num_workers: int = 1

# This creates:
# 1. A decorator named `global_pipeline_config`
# 2. A lazy class named `PipelineConfig`

@global_pipeline_config
@dataclass(frozen=True)
class WellFilterConfig:
    well_filter: Optional[Union[List[str], str, int]] = None
    well_filter_mode: WellFilterMode = WellFilterMode.INCLUDE

# After module loading, GlobalPipelineConfig now has:
# - well_filter_config: WellFilterConfig = WellFilterConfig()
# And LazyWellFilterConfig is auto-created
```

**Where to add**:
- `README.md` - Add section after "Decorator Pattern" explaining field injection
- `docs/architecture.rst` - Add detailed explanation of injection mechanism
- `docs/examples/basic.rst` - Add example showing field injection

**Key points to document**:
- Decorated classes get injected as fields into the global config
- Field name is snake_case of class name (e.g., `WellFilterConfig` → `well_filter_config`)
- Lazy version is auto-created (e.g., `LazyWellFilterConfig`)
- Injection happens at end of module loading via `_inject_all_pending_fields()`

---

### 3. **inherit_as_none Parameter**

**What it is**: Parameter for the generated decorator that sets all inherited fields to None by default, enabling proper lazy resolution.

**Signature**:
```python
@global_pipeline_config(inherit_as_none=True)  # Default is True
@dataclass(frozen=True)
class StreamingConfig(StepWellFilterConfig, StreamingDefaults, ABC):
    # All fields from StepWellFilterConfig and StreamingDefaults
    # are automatically set to None defaults for inheritance
    pass
```

**Example from OpenHCS** (`openhcs/core/config.py:443-452`):
```python
@global_pipeline_config(ui_hidden=True)
@dataclass(frozen=True)
class StreamingConfig(StepWellFilterConfig, StreamingDefaults, ABC):
    """Abstract base configuration for streaming to visualizers.

    Uses multiple inheritance from StepWellFilterConfig and StreamingDefaults.
    Inherited fields (persistent, host, port, transport_mode) are automatically set to None
    by @global_pipeline_config(inherit_as_none=True), enabling polymorphic access without
    type-specific attribute names.
    """
```

**Where to add**:
- `README.md` - Add section on decorator parameters
- `docs/architecture.rst` - Explain how inherit_as_none works with MRO
- `docs/examples/dual_axis.rst` - Show example with multiple inheritance

**Key points to document**:
- Default is `True` for the generated decorator
- Sets all inherited fields (from parent classes) to None defaults
- Only explicitly defined fields in the class keep their concrete defaults
- Critical for proper dual-axis inheritance with multiple inheritance
- Uses `InheritAsNoneMeta` metaclass internally

---

### 4. **ui_hidden Parameter**

**What it is**: Parameter that hides configs from UI while still applying decorator behavior and keeping them in the resolution context.

**Signature**:
```python
@global_pipeline_config(ui_hidden=True)
@dataclass(frozen=True)
class NapariDisplayConfig:
    # This config is hidden from UI but still available for inheritance
    pass
```

**Example from OpenHCS** (`openhcs/core/config.py:183-186`):
```python
# Apply the global pipeline config decorator with ui_hidden=True
# This config is only inherited by NapariStreamingConfig, so hide it from UI
NapariDisplayConfig = global_pipeline_config(ui_hidden=True)(NapariDisplayConfig)
```

**Where to add**:
- `README.md` - Add to decorator parameters section
- `docs/examples/ui.rst` - Add section on hiding configs from UI

**Key points to document**:
- Sets `_ui_hidden = True` on both the base class and lazy class
- Config remains in context for lazy resolution
- Decorator still creates lazy version and injects field
- UI layer checks `_ui_hidden` attribute to skip rendering
- Useful for intermediate configs that are only inherited by other configs

---

### 5. **ensure_global_config_context() Function**

**What it is**: Function that establishes the global configuration context for lazy resolution. Must be called after creating your global config instance.

**Signature**:
```python
def ensure_global_config_context(global_config_type: Type, global_config_instance: Any) -> None:
    """Ensure proper thread-local storage setup for any global config type."""
```

**Example from OpenHCS** (`openhcs/config_framework/README.md:59-67`):
```python
# 4. Set up global config
global_config = GlobalPipelineConfig(
    num_workers=8,
    path_planning_config=PathPlanningConfig(
        sub_dir="images",
        output_dir_suffix="_processed"
    )
)
ensure_global_config_context(GlobalPipelineConfig, global_config)
```

**Where to add**:
- `README.md` - Add to Quick Start section (step 4)
- `docs/quickstart.rst` - Add as required step after creating global config
- `docs/architecture.rst` - Explain difference from `set_base_config_type()`

**Key points to document**:
- **Required** for lazy resolution to work
- Must be called after creating global config instance
- Uses thread-local storage for thread safety
- Different from `set_base_config_type()`:
  - `set_base_config_type()`: Sets the **type** (class) for the framework
  - `ensure_global_config_context()`: Sets the **instance** (concrete values) for resolution
- Internally calls `set_global_config_for_editing()`
- Should be called at application startup (GUI) or before pipeline execution

---

### 6. **Automatic Nested Dataclass Lazification**

**What it is**: When creating a lazy dataclass, any nested dataclass fields are automatically converted to their lazy versions.

**Example**:
```python
@dataclass(frozen=True)
class PathPlanningConfig:
    output_dir_suffix: str = "_openhcs"
    sub_dir: str = "images"

@dataclass(frozen=True)
class GlobalPipelineConfig:
    num_workers: int = 1
    path_planning_config: PathPlanningConfig = PathPlanningConfig()

# When you create LazyPipelineConfig:
LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(PipelineConfig)

# The path_planning_config field is automatically converted to LazyPathPlanningConfig
# You don't need to manually create LazyPathPlanningConfig first
```

**Where to add**:
- `README.md` - Add note in "Simple Usage" section
- `docs/architecture.rst` - Explain automatic lazy type mapping
- `docs/examples/basic.rst` - Show example with nested configs

**Key points to document**:
- Nested dataclass fields are automatically made lazy
- No need to manually create lazy versions of nested configs first
- Uses `register_lazy_type_mapping()` internally
- Preserves field metadata (e.g., `ui_hidden` flag)
- Creates default factories for Optional dataclass fields

---

## Files to Modify

### README.md
**Changes needed**:
1. ✅ Already fixed: Factory instantiation (line 39)
2. Add section on decorator parameters (`inherit_as_none`, `ui_hidden`)
3. Add section on field injection behavior
4. Add `ensure_global_config_context()` to Quick Start
5. Add note about automatic nested dataclass lazification

### docs/index.rst
**Changes needed**:
1. Check Quick Example for factory instantiation
2. Add link to decorator parameters documentation

### docs/quickstart.rst
**Changes needed**:
1. Fix factory instantiation pattern
2. Add `ensure_global_config_context()` as required step
3. Add section on decorator parameters

### docs/architecture.rst
**Changes needed**:
1. Add section on field injection mechanism
2. Add section on `inherit_as_none` and how it works with MRO
3. Add section explaining `ensure_global_config_context()` vs `set_base_config_type()`
4. Add section on automatic nested dataclass lazification

### docs/examples/basic.rst
**Changes needed**:
1. Fix all factory instantiation patterns (lines 28-29, 67-69, 108, 146)
2. Add example showing field injection
3. Add example showing nested dataclass auto-lazification

### docs/examples/dual_axis.rst
**Changes needed**:
1. Check for factory instantiation issues
2. Add example using `inherit_as_none` with multiple inheritance

### docs/examples/ui.rst
**Changes needed**:
1. Add section on `ui_hidden` parameter
2. Show example of hiding configs from UI

---

## Verification Checklist

After making changes, verify:
- [ ] All factory instantiation uses static method (no `factory = LazyDataclassFactory()`)
- [ ] `ensure_global_config_context()` is documented as required step
- [ ] Field injection behavior is explained with examples
- [ ] `inherit_as_none` parameter is documented with multiple inheritance example
- [ ] `ui_hidden` parameter is documented
- [ ] Automatic nested dataclass lazification is explained
- [ ] All code examples are consistent with OpenHCS usage patterns
- [ ] Cross-references between docs are correct

