# Hieraconf Test Suite Assessment & Improvement Plan

**Based on**: Real-world OpenHCS usage patterns vs current hieraconf test coverage

---

## Executive Summary

**Current State**: Tests cover basic functionality but miss critical real-world usage patterns from OpenHCS.

**Gap Analysis**:
- ❌ No tests for `ensure_global_config_context()` - **CRITICAL** missing coverage
- ❌ No tests for `@auto_create_decorator` field injection behavior
- ❌ No tests for `inherit_as_none` parameter
- ❌ No tests for `ui_hidden` parameter  
- ❌ No tests for automatic nested dataclass lazification
- ❌ No tests for complete pipeline execution flow (Global → Pipeline → Step contexts)
- ❌ No tests for placeholder resolution in nested contexts
- ❌ No tests for multiple inheritance with MRO resolution
- ⚠️  Factory instantiation tests use WRONG pattern (`factory = LazyDataclassFactory()`)

**Code Coverage Estimate**: ~40% of critical paths tested

---

## Real-World Usage Patterns from OpenHCS

### Pattern 1: Application Startup (GUI/CLI)
```python
# openhcs/pyqt_gui/app.py:88-98
from openhcs.config_framework.global_config import set_global_config_for_editing
from openhcs.config_framework.lazy_factory import ensure_global_config_context
from openhcs.core.config import GlobalPipelineConfig

# Create global config
global_config = GlobalPipelineConfig()

# CRITICAL: Establish global config context for lazy dataclass resolution
set_global_config_for_editing(GlobalPipelineConfig, global_config)
ensure_global_config_context(GlobalPipelineConfig, global_config)
```

**Missing Test**: `test_application_startup_pattern()`

---

### Pattern 2: Pipeline Execution with Context Stacking
```python
# tests/integration/test_main.py:370-408
# 1. Set up global context
ensure_global_config_context(GlobalPipelineConfig, global_config)

# 2. Create pipeline config with lazy configs
pipeline_config = PipelineConfig(
    path_planning_config=LazyPathPlanningConfig(
        output_dir_suffix="_custom"
    ),
    step_well_filter_config=LazyStepWellFilterConfig(well_filter=2),
    vfs_config=None,  # Inherit from global
)

# 3. Create orchestrator (provides pipeline context)
orchestrator = PipelineOrchestrator(plate_path, pipeline_config=pipeline_config)

# 4. Compilation wraps in config_context for lazy resolution
with config_context(orchestrator.pipeline_config):
    # Compiler accesses lazy configs here
    vfs_config = orchestrator.pipeline_config.vfs_config  # Resolves from global
```

**Missing Test**: `test_pipeline_execution_context_flow()`

---

### Pattern 3: Field Injection via @auto_create_decorator
```python
# openhcs/core/config.py:101-103, 242-250
@auto_create_decorator
@dataclass(frozen=True)
class GlobalPipelineConfig:
    num_workers: int = 1

# This creates:
# - Decorator: global_pipeline_config
# - Lazy class: PipelineConfig

@global_pipeline_config
@dataclass(frozen=True)
class WellFilterConfig:
    well_filter: Optional[Union[List[str], str, int]] = None

# After _inject_all_pending_fields():
# GlobalPipelineConfig now has:
#   well_filter_config: WellFilterConfig = WellFilterConfig()
# And LazyWellFilterConfig exists
```

**Missing Test**: `test_auto_decorator_field_injection()`

---

### Pattern 4: Multiple Inheritance with inherit_as_none
```python
# openhcs/core/config.py:443-452
@global_pipeline_config(ui_hidden=True)
@dataclass(frozen=True)
class StreamingConfig(StepWellFilterConfig, StreamingDefaults, ABC):
    """Inherited fields (persistent, host, port) automatically set to None
    by @global_pipeline_config(inherit_as_none=True)."""
    pass

# StepWellFilterConfig has: well_filter, well_filter_mode
# StreamingDefaults has: persistent, host, port, transport_mode
# All inherited fields become None defaults for lazy resolution
```

**Missing Test**: `test_multiple_inheritance_with_inherit_as_none()`

---

### Pattern 5: Nested Dataclass Auto-Lazification
```python
# openhcs/core/config.py:362-373
@global_pipeline_config
@dataclass(frozen=True)
class PathPlanningConfig(WellFilterConfig):
    output_dir_suffix: str = "_openhcs"
    sub_dir: str = "images"
    # Inherits: well_filter, well_filter_mode from WellFilterConfig

# When LazyPathPlanningConfig is created:
# - well_filter field type is automatically converted to LazyWellFilterConfig
# - No need to manually create LazyWellFilterConfig first
```

**Missing Test**: `test_nested_dataclass_auto_lazification()`

---

### Pattern 6: Placeholder Resolution in UI
```python
# openhcs/pyqt_gui/widgets/shared/parameter_form_manager.py:1488-1494
# Build context stack (handles static defaults for global config editing + live context)
with self._build_context_stack(overlay, live_context=live_context):
    placeholder_text = self.service.get_placeholder_text(param_name, self.dataclass_type)
    if placeholder_text:
        PyQt6WidgetEnhancer.apply_placeholder_text(widget, placeholder_text)
```

**Missing Test**: `test_placeholder_resolution_with_nested_contexts()`

---

## Current Test Suite Analysis

### ✅ What's Covered (Partially)

1. **test_integration.py** (206 lines)
   - ✅ Basic lazy resolution with context
   - ✅ Nested contexts (Global → Pipeline → Step)
   - ✅ Explicit values override context
   - ⚠️  Uses WRONG factory pattern: `factory = LazyDataclassFactory()`

2. **test_lazy_factory.py** (169 lines)
   - ✅ Basic `make_lazy_simple()` creation
   - ✅ Field mapping registration
   - ✅ Lazy resolution with/without context
   - ⚠️  No tests for `auto_create_decorator`
   - ⚠️  No tests for field injection
   - ⚠️  No tests for `inherit_as_none`

3. **test_dual_axis_resolver.py** (139 lines)
   - ✅ Basic MRO traversal
   - ✅ Field inheritance resolution
   - ⚠️  No tests for multiple inheritance
   - ⚠️  No tests for complex MRO chains

4. **test_context_manager.py** (87 lines)
   - ✅ Basic `config_context()` usage
   - ✅ Nested contexts
   - ✅ Context cleanup
   - ⚠️  No tests for `ensure_global_config_context()`
   - ⚠️  No tests for thread-local storage

5. **test_placeholder.py** (63 lines)
   - ✅ Basic placeholder service creation
   - ⚠️  Incomplete placeholder text generation tests
   - ⚠️  No tests for nested context placeholder resolution

6. **test_auto_decorator_flow_integration.py** (54 lines)
   - ✅ Tests decorator exports lazy classes
   - ⚠️  Uses fixtures but doesn't test field injection
   - ⚠️  No tests for `inherit_as_none` or `ui_hidden`

### ❌ What's Missing (Critical Gaps)

1. **No `ensure_global_config_context()` tests**
   - This is THE most critical function for real-world usage
   - Every OpenHCS application/test calls this at startup
   - Without it, lazy resolution falls back to None

2. **No field injection tests**
   - `@auto_create_decorator` injects fields into GlobalPipelineConfig
   - This is how OpenHCS builds its config hierarchy
   - Zero test coverage for this mechanism

3. **No `inherit_as_none` tests**
   - Used extensively in OpenHCS for multiple inheritance
   - Critical for proper lazy resolution with ABCs
   - Zero test coverage

4. **No `ui_hidden` tests**
   - Used to hide intermediate configs from UI
   - Important for clean UI presentation
   - Zero test coverage

5. **No complete pipeline flow tests**
   - Real-world usage: Global → Pipeline → Step contexts
   - Tests only cover simple 2-level nesting
   - Missing orchestrator-style context provider pattern

6. **No automatic nested dataclass lazification tests**
   - Framework automatically converts nested dataclass fields to lazy
   - Critical feature, zero test coverage

---

## Proposed New Tests

### Priority 1: Critical Missing Coverage

#### `test_ensure_global_config_context.py`
```python
def test_ensure_global_config_context_basic():
    """Test establishing global config context."""
    @dataclass(frozen=True)
    class GlobalConfig:
        value: str = "global"
    
    global_config = GlobalConfig(value="test")
    ensure_global_config_context(GlobalConfig, global_config)
    
    # Verify context is accessible
    from hieraconf.global_config import get_current_global_config
    retrieved = get_current_global_config(GlobalConfig)
    assert retrieved.value == "test"

def test_lazy_resolution_requires_global_context():
    """Test that lazy resolution fails without global context."""
    @dataclass
    class MyConfig:
        value: str = "default"
    
    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)
    lazy = LazyConfig()
    
    # Without ensure_global_config_context, should return None
    assert lazy.value is None

def test_application_startup_pattern():
    """Test complete application startup pattern from OpenHCS."""
    # Mirrors openhcs/pyqt_gui/app.py:88-98
    @dataclass(frozen=True)
    class GlobalPipelineConfig:
        num_workers: int = 1
        output_dir: str = "/tmp"
    
    # Application startup
    global_config = GlobalPipelineConfig(num_workers=4, output_dir="/data")
    
    set_global_config_for_editing(GlobalPipelineConfig, global_config)
    ensure_global_config_context(GlobalPipelineConfig, global_config)
    
    # Verify lazy configs can now resolve
    LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(GlobalPipelineConfig)
    lazy = LazyPipelineConfig()
    assert lazy.num_workers == 4
    assert lazy.output_dir == "/data"
```

#### `test_auto_decorator_field_injection.py`
```python
def test_auto_decorator_creates_decorator_and_lazy_class():
    """Test @auto_create_decorator creates both decorator and lazy class."""
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalTestConfig:
        base_value: int = 1
    
    # Should create global_test_config decorator
    import sys
    module = sys.modules[GlobalTestConfig.__module__]
    assert hasattr(module, 'global_test_config')
    assert hasattr(module, 'TestConfig')  # Lazy version
    assert hasattr(module, 'LazyTestConfig')  # Also exported

def test_field_injection_into_global_config():
    """Test that decorated classes get injected as fields."""
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalAppConfig:
        app_name: str = "test"
    
    # Get the generated decorator
    import sys
    module = sys.modules[GlobalAppConfig.__module__]
    global_app_config = getattr(module, 'global_app_config')
    
    # Decorate another config
    @global_app_config
    @dataclass(frozen=True)
    class DatabaseConfig:
        host: str = "localhost"
    
    # Trigger injection
    from hieraconf.lazy_factory import _inject_all_pending_fields
    _inject_all_pending_fields()
    
    # GlobalAppConfig should now have database_config field
    assert hasattr(GlobalAppConfig, '__dataclass_fields__')
    field_names = {f.name for f in fields(GlobalAppConfig)}
    assert 'database_config' in field_names

def test_field_injection_with_ui_hidden():
    """Test field injection with ui_hidden parameter."""
    # Similar to openhcs/core/config.py:183-186
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        value: int = 1
    
    import sys
    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, 'global_config')
    
    @global_config_decorator(ui_hidden=True)
    @dataclass(frozen=True)
    class HiddenConfig:
        hidden_value: str = "hidden"
    
    # Should have _ui_hidden marker
    assert hasattr(HiddenConfig, '_ui_hidden')
    assert HiddenConfig._ui_hidden is True
    
    # Lazy version should also be hidden
    LazyHiddenConfig = getattr(module, 'LazyHiddenConfig')
    assert hasattr(LazyHiddenConfig, '_ui_hidden')
    assert LazyHiddenConfig._ui_hidden is True
```

#### `test_inherit_as_none.py`
```python
def test_inherit_as_none_sets_inherited_fields_to_none():
    """Test inherit_as_none parameter sets inherited fields to None."""
    @dataclass(frozen=True)
    class BaseConfig:
        base_field: str = "base_default"
        shared_field: int = 100
    
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        global_field: str = "global"
    
    import sys
    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, 'global_config')
    
    @global_config_decorator(inherit_as_none=True)
    @dataclass(frozen=True)
    class ChildConfig(BaseConfig):
        child_field: str = "child"
    
    # Inherited fields should have None defaults
    child = ChildConfig()
    assert child.base_field is None
    assert child.shared_field is None
    assert child.child_field == "child"  # Explicit field keeps default

def test_multiple_inheritance_with_inherit_as_none():
    """Test inherit_as_none with multiple inheritance (OpenHCS pattern)."""
    # Mirrors openhcs/core/config.py:443-452
    @dataclass(frozen=True)
    class WellFilterConfig:
        well_filter: Optional[int] = None
        well_filter_mode: str = "include"
    
    @dataclass(frozen=True)
    class StreamingDefaults:
        persistent: bool = True
        host: str = "localhost"
        port: int = 5555
    
    @auto_create_decorator
    @dataclass(frozen=True)
    class GlobalConfig:
        num_workers: int = 1
    
    import sys
    module = sys.modules[GlobalConfig.__module__]
    global_config_decorator = getattr(module, 'global_config')
    
    @global_config_decorator(ui_hidden=True)
    @dataclass(frozen=True)
    class StreamingConfig(WellFilterConfig, StreamingDefaults):
        pass
    
    # All inherited fields should be None
    streaming = StreamingConfig()
    assert streaming.well_filter is None
    assert streaming.well_filter_mode is None
    assert streaming.persistent is None
    assert streaming.host is None
    assert streaming.port is None
```

---

## Test Organization Recommendations

### Restructure Test Files

**Current**: 8 test files, some overlap, missing critical patterns

**Proposed**:
```
tests/
├── unit/
│   ├── test_lazy_factory_basic.py          # Basic make_lazy_simple
│   ├── test_auto_decorator.py              # @auto_create_decorator
│   ├── test_field_injection.py             # Field injection mechanism
│   ├── test_inherit_as_none.py             # inherit_as_none parameter
│   ├── test_ui_hidden.py                   # ui_hidden parameter
│   ├── test_dual_axis_resolver.py          # MRO resolution
│   ├── test_context_manager.py             # config_context()
│   ├── test_global_config.py               # ensure_global_config_context()
│   └── test_placeholder.py                 # Placeholder service
├── integration/
│   ├── test_application_startup.py         # Complete startup pattern
│   ├── test_pipeline_execution_flow.py     # Global → Pipeline → Step
│   ├── test_nested_dataclass_lazy.py       # Auto-lazification
│   ├── test_multiple_inheritance.py        # Complex MRO chains
│   └── test_ui_placeholder_resolution.py   # Placeholder with contexts
└── fixtures/
    ├── configs.py                          # Reusable config classes
    └── helpers.py                          # Test utilities
```

---

## Code Coverage Goals

**Current Estimate**: ~40%
**Target**: >90%

### Critical Paths to Cover

1. ✅ `LazyDataclassFactory.make_lazy_simple()` - Currently covered
2. ❌ `auto_create_decorator()` - **0% coverage**
3. ❌ `create_global_default_decorator()` - **0% coverage**
4. ❌ `_inject_all_pending_fields()` - **0% coverage**
5. ❌ `ensure_global_config_context()` - **0% coverage**
6. ✅ `config_context()` - Partially covered
7. ✅ `resolve_field_inheritance()` - Partially covered
8. ❌ `InheritAsNoneMeta` - **0% coverage**
9. ❌ Automatic nested dataclass lazification - **0% coverage**
10. ❌ `ui_hidden` parameter handling - **0% coverage**

---

## Next Steps

1. **Fix existing tests** - Change factory instantiation to static method
2. **Add Priority 1 tests** - Critical missing coverage (ensure_global_config_context, field injection, inherit_as_none)
3. **Restructure test organization** - Separate unit vs integration
4. **Add integration tests** - Complete real-world patterns from OpenHCS
5. **Measure coverage** - Run pytest-cov to verify >90% coverage
6. **Document test patterns** - Add docstrings explaining what each test validates

---

## Estimated Effort

- Fix existing tests: **2 hours**
- Add Priority 1 tests: **8 hours**
- Restructure organization: **4 hours**
- Add integration tests: **8 hours**
- Coverage measurement & gaps: **2 hours**

**Total**: ~24 hours (3 days)

