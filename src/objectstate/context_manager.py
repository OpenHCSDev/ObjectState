"""
Generic contextvars-based context management system for lazy configuration.

This module provides explicit context scoping using Python's contextvars to enable
hierarchical configuration resolution without explicit parameter passing.

Key features:
1. Explicit context scoping with config_context() manager
2. Config extraction from functions, dataclasses, and objects
3. Config merging for context hierarchy
4. Clean separation between UI windows and contexts

Key components:
- current_temp_global: ContextVar holding current merged global config
- config_context(): Context manager for creating context scopes
- extract_config_overrides(): Extract config values from any object type
- merge_configs(): Merge overrides into base config
"""

import contextvars
import functools
import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, get_type_hints
from dataclasses import fields, is_dataclass
from python_introspect import resolve_annotated, resolve_optional

logger = logging.getLogger(__name__)

# Core contextvar for current merged global config
# This holds the current context state that resolution functions can access
current_temp_global = contextvars.ContextVar('current_temp_global')

# Context type stack - tracks the types of objects pushed via config_context()
# This enables generic hierarchy inference without hardcoding specific types
# The stack is a tuple of types, ordered from outermost to innermost context
context_type_stack = contextvars.ContextVar('context_type_stack', default=())

# Context layer stack - tracks (scope_id, obj) tuples for provenance tracking
# Parallel to merged config - NOT flattened, preserves hierarchy for inheritance source lookup
# Used by get_field_provenance() to determine which scope provided a resolved value
from typing import Tuple, Optional
context_layer_stack: contextvars.ContextVar[Tuple[Tuple[str, Any], ...]] = contextvars.ContextVar(
    'context_layer_stack', default=()
)

def _merge_nested_dataclass(base, override, mask_with_none: bool = False):
    """
    Recursively merge nested dataclass fields.

    For each field in override:
    - If value is None and mask_with_none=False: skip (don't override base)
    - If value is None and mask_with_none=True: override with None (mask base)
    - If value is dataclass: recursively merge with base's value
    - Otherwise: use override value

    Args:
        base: Base dataclass instance
        override: Override dataclass instance
        mask_with_none: If True, None values override base values

    Returns:
        Merged dataclass instance
    """
    if not is_dataclass(base) or not is_dataclass(override):
        return override

    merge_values = {}
    for field_info in fields(override):
        field_name = field_info.name
        override_value = object.__getattribute__(override, field_name)
        base_value = object.__getattribute__(base, field_name)

        if override_value is None:
            if mask_with_none:
                # None overrides base value (masking mode)
                merge_values[field_name] = None
            else:
                # None means "don't override" - keep base value
                continue
        elif is_dataclass(override_value):
            # Recursively merge nested dataclass
            if base_value is not None and is_dataclass(base_value):
                merge_values[field_name] = _merge_nested_dataclass(base_value, override_value, mask_with_none)
            else:
                merge_values[field_name] = override_value
        else:
            # Concrete value - use override
            merge_values[field_name] = override_value

    # Merge with base using replace_raw to preserve None values
    # (dataclasses.replace triggers lazy resolution, baking in resolved values)
    if merge_values:
        from objectstate.lazy_factory import replace_raw
        return replace_raw(base, **merge_values)
    else:
        return base


@contextmanager
def config_context(obj, mask_with_none: bool = False, use_live_global: bool = True, scope_id: Optional[str] = None):
    """
    Create new context scope with obj's matching fields merged into base config.

    This is the universal context manager for all config context needs. It works by:
    1. Finding fields that exist on both obj and the base config type
    2. Using matching field values to create a temporary merged config
    3. Setting that as the current context

    Args:
        obj: Object with config fields (pipeline_config, step, etc.)
        mask_with_none: If True, None values override/mask base config values.
                       If False (default), None values are ignored (normal inheritance).
                       Use True when editing GlobalPipelineConfig to mask thread-local
                       loaded instance with static class defaults.
        use_live_global: If True (default), use LIVE global config (UI sees unsaved edits).
                        If False, use SAVED global config (compiler sees saved values).
        scope_id: Optional scope identifier for provenance tracking (e.g., "plate_123::step_0").
                 When provided, the (scope_id, obj) tuple is pushed to context_layer_stack
                 to enable inheritance source lookup via get_field_provenance().

    Usage:
        # UI operations (default - uses LIVE)
        with config_context(orchestrator.pipeline_config):
            # UI sees unsaved global config edits

        # Compilation (explicit - uses SAVED)
        with config_context(orchestrator.pipeline_config, use_live_global=False):
            # Compiler uses saved global config only

        # With provenance tracking
        with config_context(step, scope_id="plate_123::step_0"):
            # Layer tracked for inheritance source lookup
    """
    # Get current context as base for nested contexts, or fall back to base global config
    current_context = get_current_temp_global()
    base_config = current_context if current_context is not None else get_base_global_config(use_live=use_live_global)

    # Find matching fields between obj and base config type
    overrides = {}
    if obj is not None:
        from objectstate.config import get_base_config_type

        base_config_type = get_base_config_type()

        for field_info in fields(base_config_type):
            field_name = field_info.name
            expected_type = field_info.type

            # Check if obj has this field
            try:
                # Use object.__getattribute__ to avoid triggering lazy resolution
                if hasattr(obj, field_name):
                    value = object.__getattribute__(obj, field_name)
                    # CRITICAL: When mask_with_none=True, None values override base config
                    # This allows static defaults to mask loaded instance values
                    if value is not None or mask_with_none:
                        # When masking with None, always include the value (even if None)
                        if mask_with_none:
                            # For nested dataclasses, merge with mask_with_none=True
                            if is_dataclass(value):
                                base_value = getattr(base_config, field_name, None)
                                if base_value is not None and is_dataclass(base_value):
                                    merged_nested = _merge_nested_dataclass(base_value, value, mask_with_none=True)
                                    overrides[field_name] = merged_nested
                                else:
                                    overrides[field_name] = value
                            else:
                                overrides[field_name] = value
                        # Normal mode: only include non-None values
                        elif value is not None:
                            # Check if value is compatible (handles lazy-to-base type mapping)
                            if _is_compatible_config_type(value, expected_type):
                                # CRITICAL FIX: Do NOT call to_base_config() here!
                                # to_base_config() passes None values to base class constructor,
                                # but frozen dataclasses with non-Optional defaults substitute the
                                # default value for None. This breaks cross-hierarchy inheritance.
                                # Example: LazyWellFilterConfig(well_filter_mode=None) becomes
                                # WellFilterConfig(well_filter_mode=INCLUDE) instead of keeping None.
                                #
                                # Instead, pass lazy dataclass directly to _merge_nested_dataclass,
                                # which uses object.__getattribute__ to get raw values and correctly
                                # skips None overrides.

                                # Recursively merge nested dataclass fields
                                if is_dataclass(value):
                                    base_value = getattr(base_config, field_name, None)
                                    if base_value is not None and is_dataclass(base_value):
                                        merged_nested = _merge_nested_dataclass(base_value, value, mask_with_none=False)
                                        overrides[field_name] = merged_nested
                                    else:
                                        # No base value to merge with - convert if needed
                                        if hasattr(value, 'to_base_config'):
                                            value = value.to_base_config()
                                        overrides[field_name] = value
                                else:
                                    # Non-dataclass field, use override as-is
                                    overrides[field_name] = value
            except AttributeError:
                continue

    # Create merged config if we have overrides
    # Use replace_raw to preserve None values (dataclasses.replace triggers lazy resolution)
    if overrides:
        try:
            from objectstate.lazy_factory import replace_raw
            merged_config = replace_raw(base_config, **overrides)
            logger.debug(f"Creating config context with {len(overrides)} field overrides from {type(obj).__name__}")
        except Exception as e:
            logger.warning(f"Failed to merge config overrides from {type(obj).__name__}: {e}")
            merged_config = base_config
    else:
        merged_config = base_config
        logger.debug(f"Creating config context with no overrides from {type(obj).__name__}")

    # Track the type in the context type stack
    current_types = context_type_stack.get()
    new_types = current_types + (type(obj),) if obj is not None else current_types

    # Track (scope_id, obj) in layer stack for provenance tracking
    current_layers = context_layer_stack.get()
    new_layers = current_layers + ((scope_id, obj),) if scope_id is not None else current_layers

    merged_token = current_temp_global.set(merged_config)
    type_token = context_type_stack.set(new_types)
    layer_token = context_layer_stack.set(new_layers)
    # PERFORMANCE: Clear caches on context push (new merged config)
    clear_extract_all_configs_cache()
    from objectstate.dual_axis_resolver import clear_mro_resolution_cache
    clear_mro_resolution_cache()
    try:
        yield
    finally:
        current_temp_global.reset(merged_token)
        context_type_stack.reset(type_token)
        context_layer_stack.reset(layer_token)
        # PERFORMANCE: Clear caches on context pop
        clear_extract_all_configs_cache()
        clear_mro_resolution_cache()


def get_context_type_stack():
    """
    Get the current stack of context types (outermost to innermost).

    This enables generic hierarchy inference without hardcoding specific types.
    The stack represents the order in which config_context() calls were nested.

    Returns:
        Tuple of types representing the context hierarchy.
        Empty tuple if no context is active.

    Example:
        with config_context(global_config):      # stack = (GlobalPipelineConfig,)
            with config_context(pipeline_config):  # stack = (GlobalPipelineConfig, PipelineConfig)
                with config_context(step):         # stack = (GlobalPipelineConfig, PipelineConfig, Step)
                    types = get_context_type_stack()
                    # types == (GlobalPipelineConfig, PipelineConfig, Step)
    """
    return context_type_stack.get()


def get_context_layer_stack() -> Tuple[Tuple[str, Any], ...]:
    """
    Get the current layer stack for provenance tracking.

    Returns a tuple of (scope_id, obj) tuples, ordered from outermost to innermost.
    Only includes layers where scope_id was explicitly provided to config_context().

    Used by get_field_provenance() to determine which scope provided a resolved value.

    Returns:
        Tuple of (scope_id, obj) tuples representing the context hierarchy.
        Empty tuple if no layers with scope_ids are active.

    Example:
        with config_context(plate, scope_id="plate_123"):
            with config_context(step, scope_id="plate_123::step_0"):
                layers = get_context_layer_stack()
                # layers == (("plate_123", plate), ("plate_123::step_0", step))
    """
    return context_layer_stack.get()


@functools.lru_cache(maxsize=None)
def _normalize_type(t):
    """Normalize a type by getting its base type if it's a lazy variant.

    This function is defined here to avoid circular imports with lazy_factory.
    The actual get_base_type_for_lazy is imported lazily when needed.

    PERFORMANCE: Results are cached with lru_cache since type->base_type
    mappings are immutable after class creation.
    """
    try:
        from objectstate.lazy_factory import get_base_type_for_lazy
        return get_base_type_for_lazy(t) or t
    except ImportError:
        return t


def _is_global_type(t):
    """Check if a type is a global config type.

    This function is defined here to avoid circular imports with lazy_factory.
    """
    try:
        from objectstate.lazy_factory import is_global_config_type
        return is_global_config_type(t)
    except ImportError:
        return False


# Hierarchy registry - built from active form managers
# Maps: child_type -> parent_type (normalized base types)
# This is populated by ParameterFormManager when it registers
_known_hierarchy: dict = {}


def get_root_from_scope_key(scope_key: str) -> str:
    """Extract root (plate path) from scope_key for visibility checks.

    scope_key format:
    - Pipeline-level: just plate path (e.g., "/path/to/plate")
    - Step-level: plate_path::step_token (e.g., "/path/to/plate::step_a")
    - Global: empty string

    Returns the portion before "::" (or the whole string if no "::" present).
    """
    if not scope_key:
        return ""
    return scope_key.split("::")[0]


def is_scope_affected(target_scope_id: str | None, editing_scope_id: str | None) -> bool:
    """Check if target scope is affected by edit at editing scope.

    Uses scope_id hierarchy - no type introspection needed:
    - None/"" (global) → affects all
    - "plate_path" (pipeline) → affects same plate + all its steps
    - "plate_path::token" (step) → affects only that step

    Args:
        target_scope_id: The scope being checked for affectedness (None = global)
        editing_scope_id: The scope where the edit occurred (None = global)

    Returns:
        True if target should refresh when editing_scope changes
    """
    # Normalize None to empty string
    target = target_scope_id or ""
    editing = editing_scope_id or ""

    # Global edit affects all
    if not editing:
        return True

    # Different plate roots = not affected
    target_root = get_root_from_scope_key(target)
    editing_root = get_root_from_scope_key(editing)
    if target_root != editing_root:
        return False

    # Same root: parent affects children, not vice versa
    # editing="plate" affects target="plate::step" ✓
    # editing="plate::step" affects target="plate" ✗
    return target == editing or target.startswith(editing + "::")


def _normalize_type_for_hierarchy(t):
    """Normalize a type for hierarchy registry, but preserve lazy-global distinction.

    Normalization maps lazy types to their base types (e.g., LazyPathPlanningConfig → PathPlanningConfig).
    However, PipelineConfig → GlobalPipelineConfig is a special case: they represent DISTINCT
    hierarchy levels (pipeline overrides vs global defaults), so we must NOT collapse them.

    Rule: If normalization would produce a global type from a non-global type, keep the original.
    """
    normalized = _normalize_type(t)
    # Don't collapse lazy-to-global - they're distinct hierarchy levels
    if _is_global_type(normalized) and not _is_global_type(t):
        return t
    return normalized


def register_hierarchy_relationship(context_obj_type, object_instance_type):
    """Register that context_obj_type is the parent of object_instance_type in the hierarchy.

    Called by ParameterFormManager when a root manager registers.
    This builds up the known hierarchy from actual usage patterns.

    Args:
        context_obj_type: The parent/context type (e.g., PipelineConfig for Step editor)
        object_instance_type: The child type being edited (e.g., Step)

    Note:
        Types are normalized to base types (e.g., LazyPathPlanningConfig → PathPlanningConfig),
        but lazy-to-global normalization is prevented to preserve distinct hierarchy levels
        (PipelineConfig stays as PipelineConfig, not collapsed to GlobalPipelineConfig).
    """
    if context_obj_type is None or object_instance_type is None:
        return

    parent_base = _normalize_type_for_hierarchy(context_obj_type)
    child_base = _normalize_type_for_hierarchy(object_instance_type)

    if parent_base != child_base:
        _known_hierarchy[child_base] = parent_base
        logger.debug(f"Registered hierarchy: {parent_base.__name__} -> {child_base.__name__}")


def unregister_hierarchy_relationship(object_instance_type):
    """Remove a type from the hierarchy registry when its editor closes.

    Args:
        object_instance_type: The type to remove from the registry
    """
    child_base = _normalize_type_for_hierarchy(object_instance_type)
    if child_base in _known_hierarchy:
        del _known_hierarchy[child_base]
        logger.debug(f"Unregistered hierarchy for: {child_base.__name__}")


def get_ancestors_from_hierarchy(target_type):
    """Get all ancestor types for target_type by walking up the known hierarchy.

    Returns ancestors in order from outermost to innermost (excluding target_type itself).

    Args:
        target_type: The type to find ancestors for

    Returns:
        List of ancestor types in hierarchy order (grandparent, parent, ...)
    """
    target_base = _normalize_type_for_hierarchy(target_type)
    ancestors = []

    # Walk up the hierarchy
    current = target_base
    visited = set()
    while current in _known_hierarchy:
        if current in visited:
            # Cycle detected - stop
            break
        visited.add(current)
        parent = _known_hierarchy[current]
        ancestors.append(parent)
        current = parent

    # Reverse so outermost is first
    ancestors.reverse()
    return ancestors


def get_normalized_stack():
    """
    Get the context type stack with normalized (base) types, excluding global configs.

    Returns:
        List of base types in hierarchy order (outermost to innermost),
        with global config types filtered out.
    """
    canonical_stack = get_context_type_stack()
    normalized = []
    for t in canonical_stack:
        base_t = _normalize_type(t)
        if not _is_global_type(base_t):
            normalized.append(base_t)
    return normalized


def get_types_before_in_stack(target_type):
    """
    Get all non-global types that come before target_type in the hierarchy.

    First tries the active context_type_stack (for resolution during config_context),
    then falls back to the known hierarchy registry (for cross-window updates).

    Args:
        target_type: The type to find ancestors for (will be normalized)

    Returns:
        List of base types that come before target_type in the hierarchy.
        Empty list if no ancestors found.
    """
    # First try active context stack
    normalized_stack = get_normalized_stack()
    if normalized_stack:
        target_base = _normalize_type(target_type)

        # Find target's position
        target_index = -1
        for i, base_t in enumerate(normalized_stack):
            if base_t == target_base:
                target_index = i
                break

        if target_index > 0:
            return normalized_stack[:target_index]

    # Fall back to known hierarchy registry
    return get_ancestors_from_hierarchy(target_type)


def is_ancestor_in_context(ancestor_type, descendant_type):
    """
    Check if ancestor_type comes before descendant_type in the context hierarchy.

    This determines whether changes to ancestor_type should affect descendant_type.

    Args:
        ancestor_type: The potential ancestor type
        descendant_type: The potential descendant type

    Returns:
        True if ancestor_type is an ancestor of descendant_type,
        False otherwise.
    """
    from objectstate.lazy_factory import get_base_type_for_lazy

    # Check 1: Is ancestor_type the lazy base of descendant_type?
    # This handles GlobalPipelineConfig → PipelineConfig relationship
    # PipelineConfig is a lazy version of GlobalPipelineConfig
    descendant_base = get_base_type_for_lazy(descendant_type)
    if descendant_base is not None and descendant_base == ancestor_type:
        return True

    # Check 2: Normalize for comparison (handles nested lazy configs like LazyPathPlanningConfig)
    ancestor_base = _normalize_type(ancestor_type)
    descendant_normalized = _normalize_type(descendant_type)

    # Check 3: Active context stack (uses normalized types)
    normalized_stack = get_normalized_stack()
    if normalized_stack:
        ancestor_index = -1
        descendant_index = -1
        for i, base_t in enumerate(normalized_stack):
            if base_t == ancestor_base:
                ancestor_index = i
            if base_t == descendant_normalized:
                descendant_index = i

        if ancestor_index >= 0 and descendant_index >= 0:
            return ancestor_index < descendant_index

    # Check 4: Known hierarchy registry (uses actual types, not normalized)
    ancestors = get_ancestors_from_hierarchy(descendant_type)
    # Check if ancestor_type OR its normalized form is in the ancestor list
    return ancestor_type in ancestors or ancestor_base in [_normalize_type(a) for a in ancestors]


def is_same_type_in_context(type_a, type_b):
    """
    Check if two types are the same when normalized.

    Handles lazy vs base type equivalence.

    Args:
        type_a: First type to compare
        type_b: Second type to compare

    Returns:
        True if both types normalize to the same base type.
    """
    return _normalize_type(type_a) == _normalize_type(type_b)


# ============================================================================
# Context Stack Building (for UI placeholder resolution)
# ============================================================================


def _inject_context_layer(
    stack,
    t: type | None,
    values: dict | None,
    stored: object | None,
) -> None:
    """
    Inject a context layer into the stack.

    Handles dataclass instantiation with SimpleNamespace fallback.
    For types that can't be reconstructed from editable values alone,
    injects stored object + SimpleNamespace so type tracking works and live values win.

    Args:
        stack: ExitStack to inject into
        t: Type to instantiate (None = use SimpleNamespace)
        values: Dict of values to use (None = use stored only)
        stored: Stored object to fall back to (None = no fallback)
    """
    from types import SimpleNamespace

    if values is None:
        if stored is not None:
            stack.enter_context(config_context(stored))
        return

    # Have values - try to instantiate as dataclass, fall back to SimpleNamespace
    if t is not None and is_dataclass(t):
        try:
            stack.enter_context(config_context(t(**values)))
            return
        except Exception:
            # Dataclass ctor failed (e.g., missing required args not in form)
            # Inject stored (for type tracking) + SimpleNamespace (for values)
            if stored is not None:
                stack.enter_context(config_context(stored))
            stack.enter_context(config_context(SimpleNamespace(**values)))
            return

    # Non-dataclass or no type - use SimpleNamespace
    stack.enter_context(config_context(SimpleNamespace(**values)))


def build_context_stack(
    object_instance: object,
    ancestor_objects: list[object] | None = None,
    ancestor_objects_with_scopes: list[tuple[str, object]] | None = None,
    current_scope_id: str | None = None,
    use_live: bool = True,
):
    """
    Build a complete context stack for placeholder resolution.

    SINGLE SOURCE OF TRUTH: Uses ancestor_objects from ObjectStateRegistry as the
    sole mechanism for parent hierarchy. No separate context_obj parameter.

    Layer order (innermost to outermost when entered):
    1. Global context layer (from ancestors or thread-local)
    2. Ancestor objects (from ObjectStateRegistry.get_ancestor_objects())
    3. Current object_instance

    Args:
        object_instance: The object being edited (type used to infer global editing mode)
        ancestor_objects: List of ancestor objects from least→most specific (from ObjectStateRegistry).
                         This is the SINGLE SOURCE OF TRUTH for parent hierarchy.
                         DEPRECATED: Use ancestor_objects_with_scopes for provenance tracking.
        ancestor_objects_with_scopes: List of (scope_id, object) tuples from least→most specific.
                                      Enables provenance tracking via context_layer_stack.
        current_scope_id: Scope ID for the current object_instance. Used for provenance tracking.

    Returns:
        ExitStack with all context layers entered. Caller must manage the stack lifecycle.
    """
    from contextlib import ExitStack
    from objectstate.lazy_factory import GlobalConfigBase

    stack = ExitStack()
    obj_type = type(object_instance)

    # Infer global editing mode from object_instance type
    is_global_config_editing = isinstance(object_instance, GlobalConfigBase)

    obj_type_name = obj_type.__name__

    # PERFORMANCE: Only build ancestor list for logging when DEBUG is enabled
    if logger.isEnabledFor(logging.DEBUG):
        if ancestor_objects_with_scopes:
            ancestor_types = [type(o).__name__ for _, o in ancestor_objects_with_scopes]
        elif ancestor_objects:
            ancestor_types = [type(o).__name__ for o in ancestor_objects]
        else:
            ancestor_types = []
        logger.debug(f"🔧 build_context_stack: obj={obj_type_name}, ancestors={ancestor_types}")

    # 1. Global context layer (least specific)
    # ALWAYS use LIVE thread-local for global config - it's the SINGLE SOURCE OF TRUTH
    # Don't use ancestor_objects for GlobalConfigBase since that comes from to_object()
    # which can be stale relative to the LIVE thread-local we just updated.
    if is_global_config_editing:
        try:
            global_layer = obj_type()  # Fresh instance with static defaults
            stack.enter_context(config_context(global_layer, mask_with_none=True, scope_id=""))
        except Exception:
            pass  # Couldn't create global layer
    else:
        # Use LIVE or SAVED thread-local based on use_live parameter
        global_layer = get_base_global_config(use_live=use_live)
        if global_layer:
            stack.enter_context(config_context(global_layer, scope_id=""))

    # 2. Ancestor objects (intermediate layers, excluding GlobalConfigBase already handled)
    if ancestor_objects_with_scopes:
        # New format with scope_ids for provenance tracking
        for scope_id, ancestor_obj in ancestor_objects_with_scopes:
            if isinstance(ancestor_obj, GlobalConfigBase):
                continue
            stack.enter_context(config_context(ancestor_obj, scope_id=scope_id))
    elif ancestor_objects:
        # Legacy format without scope_ids
        for ancestor_obj in ancestor_objects:
            if isinstance(ancestor_obj, GlobalConfigBase):
                continue
            stack.enter_context(config_context(ancestor_obj))

    # 3. Current object overlay (most specific)
    stack.enter_context(config_context(object_instance, scope_id=current_scope_id))

    return stack


def _get_global_context_layer(
    live_context: dict | None,
    is_global_config_editing: bool,
    global_config_type: type | None,
) -> object | None:
    """
    Get the global context layer for the stack.

    Priority:
    1. If editing global config, use static defaults (mask_with_none will mask thread-local)
    2. If live_context has a global config, use that (from another open editor)
    3. Fall back to thread-local global config

    PERFORMANCE OPTIMIZATION: Within a dispatch cycle, the GLOBAL layer is cached
    since it's the same for all sibling refreshes.

    Args:
        live_context: Dict mapping types to their live values
        is_global_config_editing: True if editing a global config
        global_config_type: The global config type

    Returns:
        Global config instance to use, or None if not available
    """
    layer = None

    # 1) Global config editing → fresh instance (mask thread-local when entering)
    if is_global_config_editing and global_config_type is not None:
        try:
            layer = global_config_type()
        except Exception:
            layer = None

    # 2) Live global from other window
    if layer is None:
        layer = _find_live_global(live_context)

    # 3) Fallback to thread-local base
    if layer is None:
        layer = get_base_global_config()

    return layer


def _find_live_global(live_context: dict | None) -> object | None:
    """Find and instantiate a global config from live_context if present."""
    if not live_context:
        return None

    from objectstate.lazy_factory import is_global_config_type

    for config_type, config_values in live_context.items():
        if is_global_config_type(config_type):
            try:
                return config_type(**config_values)
            except Exception:
                continue
    return None





def _find_live_values_for_type(target_type: type, live_context: dict) -> dict | None:
    """
    Find live values for a target type in live_context.

    Handles type normalization (lazy vs base types) AND inheritance.
    For sibling inheritance, a StepWellFilterConfig's values should be
    usable when resolving WellFilterConfig's placeholders.

    IMPORTANT: Prefers subclass matches over exact matches.
    This ensures StepWellFilterConfig values (with concrete value) are used
    for WellFilterConfig resolution, not WellFilterConfig values (with None).

    Args:
        target_type: The type to find values for
        live_context: Dict mapping types to their live values

    Returns:
        Dict of field values, or None if not found
    """
    target_base = _normalize_type(target_type)
    logger.debug(f"_find_live_values_for_type: target={target_type.__name__} -> base={target_base.__name__}")
    logger.debug(f"_find_live_values_for_type: live_context has {len(live_context)} types")

    # Pass 0: exact type match without normalization (prefer most specific)
    for config_type, config_values in live_context.items():
        if config_type == target_type:
            logger.debug(f"_find_live_values_for_type: ✅ exact type match for {config_type.__name__}")
            return config_values

    # First pass: look for subclass match (more specific wins) after normalization
    # e.g., StepWellFilterConfig values for WellFilterConfig resolution
    for config_type, config_values in live_context.items():
        config_base = _normalize_type(config_type)
        try:
            if config_base != target_base and issubclass(config_base, target_base):
                logger.debug(f"_find_live_values_for_type: ✅ using {config_base.__name__} values for {target_base.__name__} (subclass)")
                return config_values
        except TypeError:
            pass  # Not a class

    # Second pass: exact type match (after normalization)
    for config_type, config_values in live_context.items():
        config_base = _normalize_type(config_type)
        if config_base == target_base:
            logger.debug(f"_find_live_values_for_type: ✅ exact match for {target_base.__name__}")
            return config_values

    logger.debug(f"_find_live_values_for_type: ❌ no match for {target_base.__name__}")
    return None


# Removed: extract_config_overrides - no longer needed with field matching approach


def extract_from_dataclass_fields(obj) -> Dict[str, Any]:
    """
    Get non-None fields as config overrides.
    
    This extracts concrete values from dataclass instances, ignoring None values
    which represent fields that should inherit from context.
    
    Args:
        obj: Dataclass instance to extract field values from
        
    Returns:
        Dict of field_name -> value for non-None fields
    """
    if not is_dataclass(obj):
        return {}
        
    overrides = {}
    
    for field in fields(obj):
        value = getattr(obj, field.name)
        if value is not None:
            overrides[field.name] = value
            
    logger.debug(f"Extracted {len(overrides)} overrides from dataclass {type(obj).__name__}")
    return overrides


def extract_from_object_attributes(obj) -> Dict[str, Any]:
    """
    Extract config attributes from step/pipeline objects.
    
    This handles orchestrators, steps, and other objects that have *_config attributes.
    It flattens the config hierarchy into a single dict of field overrides.
    
    Args:
        obj: Object to extract config attributes from
        
    Returns:
        Dict of field_name -> value for all non-None config fields
    """
    overrides = {}
    
    try:
        for attr_name in dir(obj):
            if attr_name.endswith('_config'):
                attr_value = getattr(obj, attr_name)
                if attr_value is not None and is_dataclass(attr_value):
                    # Extract all non-None fields from this config
                    config_overrides = extract_from_dataclass_fields(attr_value)
                    overrides.update(config_overrides)
                    
        logger.debug(f"Extracted {len(overrides)} overrides from object {type(obj).__name__}")
        
    except Exception as e:
        logger.debug(f"Error extracting from object {obj}: {e}")
        
    return overrides


def merge_configs(base, overrides: Dict[str, Any]):
    """
    Merge overrides into base config, creating new immutable instance.
    
    This creates a new config instance with override values merged in,
    preserving immutability of the original base config.
    
    Args:
        base: Base config instance (base config type)
        overrides: Dict of field_name -> value to override
        
    Returns:
        New config instance with overrides applied
    """
    if not base or not overrides:
        return base

    try:
        # CRITICAL: Do NOT filter out None values!
        # None can be a semantic value such as "inherit from parent context".
        # When an override dict contains None, it means "reset this field to None"
        # which should override the base value with None for lazy resolution.

        if not overrides:
            return base

        # Use replace_raw to preserve None values (dataclasses.replace triggers lazy resolution)
        from objectstate.lazy_factory import replace_raw
        merged = replace_raw(base, **overrides)

        logger.debug(f"Merged {len(overrides)} overrides into {type(base).__name__}")
        return merged
        
    except Exception as e:
        logger.warning(f"Failed to merge configs: {e}")
        return base


def get_base_global_config(use_live: bool = True):
    """
    Get the base global config (fallback when no context set).

    This provides the global config that was set up with ensure_global_config_context(),
    or a default if none was set. Used as the base for merging operations.

    Args:
        use_live: If True (default), return LIVE config (UI sees unsaved edits).
                 If False, return SAVED config (compiler sees saved values).

    Returns:
        Current global config instance or default instance of base config type
    """
    try:
        from objectstate.config import get_base_config_type
        from objectstate.global_config import get_current_global_config

        base_config_type = get_base_config_type()

        # Get the appropriate global config (live or saved)
        current_global = get_current_global_config(base_config_type, use_live=use_live)
        if current_global is not None:
            # DEBUG: Log well_filter value
            try:
                wf_value = object.__getattribute__(current_global.well_filter_config, 'well_filter')
                logger.debug(f"🔍 get_base_global_config: use_live={use_live}, well_filter={wf_value}")
            except:
                pass
            return current_global

        # Fallback to default if none was set
        return base_config_type()
    except ImportError:
        logger.warning("Could not get base config type")
        return None


def get_current_temp_global():
    """
    Get current context or None.
    
    This is the primary interface for resolution functions to access
    the current context. Returns None if no context is active.
    
    Returns:
        Current merged global config or None
    """
    return current_temp_global.get(None)


def set_current_temp_global(config):
    """
    Set current context (for testing/debugging).
    
    This is primarily for testing purposes. Normal code should use
    config_context() manager instead.
    
    Args:
        config: Global config instance to set as current context
        
    Returns:
        Token for resetting the context
    """
    return current_temp_global.set(config)


def clear_current_temp_global():
    """
    Clear current context (for testing/debugging).
    
    This removes any active context, causing resolution to fall back
    to default behavior.
    """
    try:
        current_temp_global.set(None)
    except LookupError:
        pass  # No context was set


# Utility functions for debugging and introspection

def get_context_info() -> Dict[str, Any]:
    """
    Get information about current context for debugging.
    
    Returns:
        Dict with context information including type, field count, etc.
    """
    current = get_current_temp_global()
    if current is None:
        return {"active": False}
        
    return {
        "active": True,
        "type": type(current).__name__,
        "field_count": len(fields(current)) if is_dataclass(current) else 0,
        "non_none_fields": sum(1 for f in fields(current) 
                              if getattr(current, f.name) is not None) if is_dataclass(current) else 0
    }


def extract_all_configs_from_context() -> Dict[type, Any]:
    """
    Extract all *_config attributes from current context.

    This is used by the resolution system to get all available configs
    for cross-dataclass inheritance resolution.

    Returns:
        Dict of config type -> config instance.
    """
    current = get_current_temp_global()
    if current is None:
        return {}

    return extract_all_configs(current)


# PERFORMANCE: Cache extracted configs per context object id
# Cleared when context changes (config_context push/pop)
_extract_all_configs_cache: Dict[int, Dict[type, Any]] = {}


def extract_all_configs(context_obj) -> Dict[type, Any]:
    """
    Extract all config instances from a context object using type-driven approach.

    PERFORMANCE: Results are cached per context object id. Cache is cleared on
    context changes via clear_extract_all_configs_cache().

    This function leverages dataclass field type annotations to efficiently extract
    config instances, avoiding string matching and runtime attribute scanning.

    Args:
        context_obj: Object to extract configs from (orchestrator, merged config, etc.)

    Returns:
        Dict mapping nominal config types to config instances.
    """
    if context_obj is None:
        return {}

    # PERFORMANCE: Check cache first
    obj_id = id(context_obj)
    if obj_id in _extract_all_configs_cache:
        return _extract_all_configs_cache[obj_id]

    configs: Dict[type, Any] = {}

    # Include the context object itself if it's a dataclass
    if is_dataclass(context_obj):
        _record_config_instance(configs, context_obj, source="context object")

    # Type-driven extraction: Use dataclass field annotations to find config fields
    if is_dataclass(type(context_obj)):
        annotations = get_type_hints(type(context_obj), include_extras=True)
        for field_info in fields(type(context_obj)):
            field_type = annotations.get(field_info.name, field_info.type)
            field_name = field_info.name

            actual_type = resolve_optional(resolve_annotated(field_type))

            # Only process fields that are dataclass types (config objects)
            if is_dataclass(actual_type):
                field_value = getattr(context_obj, field_name)
                if field_value is None:
                    continue
                if not _is_compatible_config_type(field_value, actual_type):
                    raise TypeError(
                        f"{type(context_obj).__name__}.{field_name} declares "
                        f"{actual_type.__name__}, got {type(field_value).__name__}."
                    )
                _record_config_instance(
                    configs,
                    field_value,
                    source=f"{type(context_obj).__name__}.{field_name}",
                )

    # For non-dataclass objects (orchestrators, etc.), extract dataclass attributes
    else:
        _extract_from_object_attributes_typed(context_obj, configs)

    # Cache result
    _extract_all_configs_cache[obj_id] = configs
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Extracted %d configs: %s",
            len(configs),
            [config_type.__name__ for config_type in configs],
        )
    return configs


def clear_extract_all_configs_cache() -> None:
    """Clear the extract_all_configs cache. Call when context changes."""
    _extract_all_configs_cache.clear()


def _record_config_instance(
    configs: Dict[type, Any],
    config_instance: Any,
    *,
    source: str,
) -> None:
    """Record one nominal config identity and reject ambiguous duplicates."""

    from objectstate.lazy_factory import get_base_type_for_lazy

    instance_type = type(config_instance)
    base_type = get_base_type_for_lazy(instance_type) or instance_type
    existing = configs.get(base_type)
    if existing is not None and existing is not config_instance:
        raise ValueError(
            f"{source} introduces a second {base_type.__name__} instance into "
            "one configuration context."
        )
    configs[base_type] = config_instance


def _extract_from_object_attributes_typed(obj, configs: Dict[type, Any]) -> None:
    """
    Type-safe extraction from object attributes for non-dataclass objects.

    This is used for orchestrators and other objects that aren't dataclasses
    but have config attributes. Uses type checking instead of string matching.
    """
    for attr_name in dir(obj):
        if attr_name.startswith('_'):
            continue

        try:
            attr_value = getattr(obj, attr_name)
        except (AttributeError, TypeError):
            continue
        if attr_value is not None and is_dataclass(attr_value):
            _record_config_instance(
                configs,
                attr_value,
                source=f"{type(obj).__name__}.{attr_name}",
            )
            logger.debug(
                "Extracted config %s from attribute %s",
                type(attr_value).__name__,
                attr_name,
            )


def _is_compatible_config_type(value, expected_type) -> bool:
    """
    Check if value is compatible with expected_type, handling lazy-to-base type mapping.

    This handles cases where:
    - value is LazyStepMaterializationConfig, expected_type is StepMaterializationConfig
    - value is a subclass of the expected type
    - value is exactly the expected type
    """
    from objectstate.lazy_factory import get_base_type_for_lazy

    expected_type = resolve_optional(resolve_annotated(expected_type))
    if not isinstance(expected_type, type):
        return False
    value_type = type(value)
    value_base = get_base_type_for_lazy(value_type) or value_type
    expected_base = get_base_type_for_lazy(expected_type) or expected_type
    return issubclass(value_base, expected_base)


def spawn_thread_with_context(
    target,
    daemon: bool = True,
    name: str = None,
    *args,
    **kwargs,
):
    """Spawn a thread with current context propagated.

    This ensures thread-local context (like GlobalPipelineConfig from
    config framework) is accessible in spawned thread.

    Python's threading module creates isolated thread-local storage, so contextvars
    don't automatically propagate to spawned threads. This utility wraps
    threading.Thread to propagate the current context using contextvars.copy_context().

    Args:
        target: The function to run in thread
        daemon: Whether thread should be a daemon thread (default: True)
        name: Optional thread name
        *args: Positional arguments to pass to target
        **kwargs: Keyword arguments to pass to target

    Returns:
        The spawned Thread object

    Example:
        >>> spawn_thread_with_context(my_function, arg1, kwarg=value)
        >>> # Equivalent to:
        >>> ctx = contextvars.copy_context()
        >>> threading.Thread(target=ctx.run, args=(my_function, arg1), kwargs={'kwarg': value}).start()
    """
    ctx = contextvars.copy_context()
    thread = threading.Thread(
        target=lambda: ctx.run(target, *args, **kwargs),
        daemon=daemon,
        name=name,
    )
    thread.start()
    return thread
