# N-Dimensional Inheritance via Context Stacking

## Problem Statement

ObjectState currently supports 2D inheritance:
- **X-axis**: Context hierarchy (Step → Pipeline → Global)
- **Y-axis**: MRO traversal within each context

We want to add orthogonal dimensions (e.g., User → Team → Org) that resolve through the **same mechanism** without hardcoding dimension logic.

## Key Insight

**N-dimensional inheritance is just context stacking with different config types.**

The existing `config_context()` already supports this - we just need to:
1. Push organizational configs onto the same stack
2. Ensure resolution respects the stacking order
3. Add provenance tracking to identify which "dimension" provided the value

## Current Architecture (Correct Usage)

```python
# Current 2D: Execution contexts stack naturally
with config_context(global_config):          # Base
    with config_context(pipeline_config):    # Override
        with config_context(step_config):    # Override
            lazy = LazyStepConfig()
            # Resolution: step → pipeline → global
```

## Proposed: N-Dimensional via Context Stacking

```python
# N-dimensional: Different config types on same stack
with config_context(org_config):             # Org dimension
    with config_context(team_config):        # Team dimension
        with config_context(user_config):     # User dimension
            with config_context(global_config):   # Execution dimension
                with config_context(pipeline_config):
                    with config_context(step_config):
                        lazy = LazyStepConfig()
                        # Resolution walks entire stack:
                        # step → pipeline → global → user → team → org
```

## The Fix: Config Type Discrimination

**Problem**: Current resolution doesn't distinguish between config types. It flattens everything into `available_configs` by type name.

**Solution**: Add config type categories so resolution can prioritize within categories while still stacking across categories.

### Implementation

```python
# In objectstate/config.py - add type categorization

from dataclasses import dataclass
from typing import Type, Optional
from enum import Enum, auto

class ConfigDimension(Enum):
    """Dimensions for orthogonal inheritance.
    
    These are NOT separate stacks - they're type categories
    that determine resolution priority within the unified stack.
    """
    EXECUTION = auto()       # Step, Pipeline, Global
    ORGANIZATIONAL = auto()  # User, Team, Org
    ENVIRONMENT = auto()     # Local, Staging, Prod
    # Future dimensions can be added without code changes

# Type registry with dimension metadata
_config_type_dimensions: Dict[Type, ConfigDimension] = {}

def register_config_type(config_type: Type, dimension: ConfigDimension):
    """Register a config type as belonging to a dimension."""
    _config_type_dimensions[config_type] = dimension

def get_config_dimension(config_type: Type) -> Optional[ConfigDimension]:
    """Get dimension for a config type, or None if not registered."""
    return _config_type_dimensions.get(config_type)
```

### Modified Resolution Algorithm

```python
# In objectstate/object_state.py - modify resolution

def _get_available_configs_for_resolution(self) -> Dict[Type, Any]:
    """
    Build available configs dict respecting dimension priority.
    
    Instead of flat dict, organize by dimension priority:
    - Within each dimension: most specific context wins
    - Across dimensions: higher priority dimension wins
    """
    from objectstate.context_manager import get_context_layer_stack
    from objectstate.config import get_config_dimension, ConfigDimension
    
    # Get raw context stack (preserves order: outermost to innermost)
    layer_stack = get_context_layer_stack()
    
    # Group contexts by dimension
    configs_by_dimension: Dict[ConfigDimension, Dict[Type, Any]] = {}
    
    for scope_id, context_obj in layer_stack:
        context_type = type(context_obj)
        dimension = get_config_dimension(context_type)
        
        if dimension is None:
            # Backward compatibility: default to execution dimension
            dimension = ConfigDimension.EXECUTION
        
        if dimension not in configs_by_dimension:
            configs_by_dimension[dimension] = {}
        
        # Within dimension, later (more specific) contexts override earlier ones
        configs_by_dimension[dimension][context_type] = context_obj
    
    # Build final available_configs respecting dimension priority
    # Lower enum value = higher priority
    available_configs = {}
    for dimension in sorted(ConfigDimension, key=lambda d: d.value):
        if dimension in configs_by_dimension:
            # This dimension's configs override lower priority dimensions
            available_configs.update(configs_by_dimension[dimension])
    
    return available_configs
```

## Usage Example: OpenHCS Organizational Dimension

```python
# openhcs/core/config.py

from dataclasses import dataclass
from objectstate import register_config_type, ConfigDimension

@dataclass
class OrgConfig:
    compliance_mode: bool = None
    audit_logging: bool = None

@dataclass
class TeamConfig:
    default_output_dir: str = None
    shared_well_filter: str = None

@dataclass
class UserProfileConfig:
    num_workers: int = None
    debug_mode: bool = None
    preferred_colormap: str = None

# Register with organizational dimension
register_config_type(OrgConfig, ConfigDimension.ORGANIZATIONAL)
register_config_type(TeamConfig, ConfigDimension.ORGANIZATIONAL)
register_config_type(UserProfileConfig, ConfigDimension.ORGANIZATIONAL)

# Execution configs already default to EXECUTION dimension
# (backward compatible - existing code works unchanged)
```

### Application Integration

```python
# openhcs/pyqt_gui/main.py - load user/team/org on startup

class OpenHCSMainWindow:
    def __init__(self):
        # ... existing init ...
        
        # Load organizational contexts
        self._load_organizational_contexts()
    
    def _load_organizational_contexts(self):
        """Push org/team/user configs onto the context stack."""
        # These persist for the entire session
        # (could be refreshed on user switch)
        
        org_config = self._load_org_config()
        team_config = self._load_team_config()
        user_config = self._load_user_profile()
        
        # Push onto context stack - these stay for entire session
        with config_context(org_config, scope_id="org"):
            with config_context(team_config, scope_id="team"):
                with config_context(user_config, scope_id="user"):
                    # Now all subsequent contexts inherit from these
                    self._run_application()
```

### Resolution Order

```python
# With the above setup:

with config_context(org_config):           # Dimension: ORGANIZATIONAL, priority 2
    with config_context(team_config):      # Dimension: ORGANIZATIONAL, priority 2
        with config_context(user_config):  # Dimension: ORGANIZATIONAL, priority 2
            with config_context(global_config):      # Dimension: EXECUTION, priority 1
                with config_context(pipeline_config): # Dimension: EXECUTION, priority 1
                    lazy = LazyStepConfig()
                    
                    # Resolution order (higher priority first):
                    # 1. EXECUTION dimension (priority 1):
                    #    - pipeline_config (most specific)
                    #    - global_config
                    # 2. ORGANIZATIONAL dimension (priority 2):
                    #    - user_config (most specific)
                    #    - team_config
                    #    - org_config
                    
                    print(lazy.num_workers)  # Checks in order above
```

**Wait - this is wrong!** Higher priority should be checked first. Let me fix:

```python
class ConfigDimension(Enum):
    """Lower value = higher priority (checked first)."""
    EXECUTION = 1       # Most specific, checked first
    ENVIRONMENT = 2     # Override execution if set
    ORGANIZATIONAL = 3  # Override environment if set
```

Actually, thinking about it more carefully:

The correct semantics should be:
- **EXECUTION** (Step → Pipeline → Global): Most specific runtime context
- **ORGANIZATIONAL** (User → Team → Org): User preferences override system defaults

So if PipelineConfig sets `num_workers=8` and UserProfile sets `num_workers=4`:
- Execution dimension has priority (runtime configuration)
- So `num_workers=8` wins

But wait - the user's intent is probably that their personal preference (UserProfile) overrides the pipeline. So organizational should have HIGHER priority.

Let me reconsider the priority semantics...

Actually, looking at CSS specificity (the model we're emulating):
- User stylesheet (organizational) has higher priority than page stylesheet (execution)
- But inline styles (step-level) have highest priority

So the priority should be:
1. Step (inline) - highest
2. User/Team/Org (user stylesheet)
3. Pipeline/Global (page stylesheet) - lowest

But within each category, inheritance still applies.

So the resolution is:
1. Check execution dimension (step → pipeline → global)
2. If not found, check organizational (user → team → org)
3. If not found, use dataclass default

Wait no - that's wrong. We want organizational to OVERRIDE execution, not be a fallback.

Correct semantics:
- UserProfile.num_workers = 4 should override PipelineConfig.num_workers = 8
- Unless PipelineConfig explicitly sets it (then it wins due to being more specific)

Hmm, this is getting complex. Let me think about this differently.

The key insight from CSS:
- !important (dimension override) > specificity (inheritance depth) > source order

So dimensions are like !important - they win over inheritance depth within other dimensions.

Correct resolution:
1. Within highest priority dimension: walk inheritance chain (most specific wins)
2. If not found: next priority dimension
3. Continue until default

Priority order (highest first):
1. ORGANIZATIONAL (user preferences are king)
2. ENVIRONMENT (deployment-specific overrides)
3. EXECUTION (runtime pipeline config)
4. DEFAULT (dataclass defaults)

```python
class ConfigDimension(Enum):
    """Lower value = higher priority (checked first)."""
    ORGANIZATIONAL = 1  # User preferences override everything
    ENVIRONMENT = 2     # Deployment-specific settings
    EXECUTION = 3       # Runtime pipeline configuration
```

Example:
```python
# Priority 1 (ORGANIZATIONAL)
UserProfile: num_workers=4, debug_mode=True
TeamConfig: num_workers=8, shared_filter="A01"
OrgConfig: compliance_mode=True

# Priority 2 (ENVIRONMENT)  
LocalDevConfig: use_gpu=False

# Priority 3 (EXECUTION)
PipelineConfig: num_workers=16
StepConfig: well_filter="B02"

# Resolution:
LazyStepConfig().num_workers
# 1. Check ORGANIZATIONAL: UserProfile has num_workers=4 → return 4
# (User preference overrides pipeline's num_workers=16)

LazyStepConfig().well_filter
# 1. Check ORGANIZATIONAL: No one has well_filter → continue
# 2. Check ENVIRONMENT: No one has well_filter → continue
# 3. Check EXECUTION: StepConfig has well_filter="B02" → return "B02"

LazyStepConfig().compliance_mode
# 1. Check ORGANIZATIONAL: OrgConfig has compliance_mode=True → return True
# (Org policy applies regardless of execution context)
```

This makes sense! User/team/org settings act as **overrides** that take precedence over the execution pipeline. But execution settings still work for fields not overridden by the user.

## Provenance Tracking

With dimensions, provenance needs to show WHICH dimension provided the value:

```python
# Enhanced provenance tracking
@dataclass
class FieldProvenance:
    field_name: str
    value: Any
    scope_id: str           # "step_0", "user_john", etc.
    dimension: ConfigDimension  # EXECUTION, ORGANIZATIONAL, etc.
    context_type: Type      # StepConfig, UserProfile, etc.
```

UI shows:
- `num_workers: 4 (from UserProfile, Organizational)`
- `well_filter: "B02" (from StepConfig, Execution)`
- `compliance_mode: True (from OrgConfig, Organizational - policy enforced)`

## No Code Changes to Core Resolution (Almost)

The beautiful part: we only need to:

1. **Add dimension metadata** to config types (registration)
2. **Modify `_get_available_configs`** to sort by dimension priority
3. **Everything else works unchanged** - MRO, dirty tracking, flash callbacks, etc.

The context manager doesn't change. The config_context() usage doesn't change. The LazyDataclassFactory doesn't change.

## Backward Compatibility

```python
# Existing code: all configs default to EXECUTION dimension
# No registration needed - they work exactly as before

with config_context(global_config):
    with config_context(pipeline_config):
        lazy = LazyConfig()
        # Still works, defaults to EXECUTION dimension

# New code: opt-in to other dimensions
register_config_type(UserProfileConfig, ConfigDimension.ORGANIZATIONAL)

with config_context(user_config):
    with config_context(global_config):
        lazy = LazyConfig()
        # Now organizational contexts are checked first
```

## Implementation Checklist

- [ ] Add `ConfigDimension` enum
- [ ] Add config type registration functions
- [ ] Modify `_get_available_configs` to group by dimension
- [ ] Update provenance tracking to include dimension
- [ ] Update UI to show dimension in tooltips
- [ ] Tests for cross-dimensional resolution
- [ ] Documentation for adding new dimensions

## Summary

N-dimensional inheritance isn't a new abstraction - it's just **type-categorized context stacking**. The existing `config_context()` mechanism is perfect; we just needed to add metadata so resolution knows which contexts are "more important" than others.

This approach:
- ✅ Uses existing context manager (no new abstractions)
- ✅ Leverages existing resolution mechanism
- ✅ Backward compatible (unregistered types default to EXECUTION)
- ✅ Extensible (add new dimensions without core changes)
- ✅ Maintains all existing features (dirty tracking, flash, provenance)

The "dimensions" are just categories that determine priority in the unified resolution stack.
