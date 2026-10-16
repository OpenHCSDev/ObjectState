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
- merge_configs(): Merge overrides into base config
"""

import contextvars
import functools
import logging
import threading
from collections.abc import Sequence
from contextlib import ExitStack, contextmanager
from typing import Any, Dict, get_type_hints
from python_introspect import resolve_annotated, resolve_optional
from objectstate.field_access import DataclassFieldAccess
from objectstate.field_value import FieldValue
from objectstate.declarations import ValueDeclaration, admit_root_value
from objectstate.construction_binding import admit_target
from python_introspect import resolve_declared_type

logger = logging.getLogger(__name__)


class NoActiveContextError(RuntimeError):
    """A field was resolved against the active context while no context was active."""


# Core contextvar for current merged global config
# This holds the current context state that resolution functions can access
current_temp_global = contextvars.ContextVar('current_temp_global')

# Context type stack - tracks the types of objects pushed via config_context()
# This enables generic hierarchy inference without hardcoding specific types
# The stack is a tuple of types, ordered from outermost to innermost context
context_type_stack = contextvars.ContextVar('context_type_stack', default=())

class ContextLayer:
    """One object entered with ``config_context``, with the scope it was entered under.

    ``scope_id`` is ``None`` for a layer entered without one.
    """

    __slots__ = ("scope_id", "value", "_configs")

    def __init__(self, scope_id: str | None, obj: Any):
        self.scope_id = scope_id
        self.value = admit_target(obj)
        self._configs: dict[type, Any] | None = None

    @property
    def configs(self) -> dict[type, Any]:
        """The config instances this layer holds, by type. Extracted once per layer."""
        configs = self._configs
        if configs is None:
            configs = self._configs = self.value.context_configs()
        return configs

    def __repr__(self) -> str:
        return f"ContextLayer({self.scope_id!r}, {type(self.value.stored).__name__})"


class ContextLayerStack:
    """The layers of one active context, outermost first.

    This is the value field resolution reads. Every ``config_context`` entry makes a
    new stack, and ``resolved_fields`` holds the answers computed from that stack, so
    the answers are dropped together with the stack they belong to.
    """

    __slots__ = ("layers", "resolved_fields", "__weakref__")

    def __init__(self, layers: tuple[ContextLayer, ...] = ()):
        self.layers = layers
        self.resolved_fields: dict[tuple[type, str], Any] = {}

    def with_layer(self, layer: ContextLayer) -> "ContextLayerStack":
        return ContextLayerStack(self.layers + (layer,))

    def __repr__(self) -> str:
        return f"ContextLayerStack({self.layers!r})"


NO_LAYERS = ContextLayerStack()

# The layer stack of the active context. NO_LAYERS means no context is active.
context_layer_stack: contextvars.ContextVar[ContextLayerStack] = contextvars.ContextVar(
    'context_layer_stack', default=NO_LAYERS
)





@contextmanager
def config_context(obj, use_live_global: bool = True, scope_id: str | None = None):
    """Enter one admitted layer; field members own merge and raw-read behavior."""
    from objectstate.config import get_base_config_type

    current = get_current_temp_global()
    base = admit_root_value(current if current is not None else get_base_global_config(use_live=use_live_global))
    incoming = admit_target(obj)
    overrides = {}
    if obj is not None:
        global_declaration = ValueDeclaration.of(get_base_config_type())
        for name in incoming.declaration.parameters.keys() & global_declaration.parameters.keys():
            overrides[name] = incoming.read_raw(name).overlay(base.read_raw(name))
    merged = base.with_fields(overrides).stored if overrides else base.stored
    types = context_type_stack.get()
    stack = context_layer_stack.get() if current is not None else ContextLayerStack((ContextLayer('', base),))
    if obj is not None:
        stack = stack.with_layer(ContextLayer(scope_id, incoming))
        types += (type(incoming.stored),)
    with ExitStack() as resources:
        for variable, value in ((current_temp_global, merged), (context_type_stack, types), (context_layer_stack, stack)):
            resources.callback(variable.reset, variable.set(value))
        yield merged


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


def get_context_layer_stack() -> ContextLayerStack:
    """
    Get the layer stack of the active context: the value field resolution reads.

    ``.layers`` holds one ``ContextLayer`` per object entered with ``config_context``,
    outermost first, below the global config the context started from. It is empty
    when no context is active.

    Example:
        with config_context(plate, scope_id="plate_123"):
            with config_context(step, scope_id="plate_123::step_0"):
                scopes = [layer.scope_id for layer in get_context_layer_stack().layers]
                # scopes == ["", "plate_123", "plate_123::step_0"]
    """
    return context_layer_stack.get()




def _is_global_type(t):
    """Check if a type is a global config type.

    This function is defined here to avoid circular imports with lazy_factory.
    """
    from objectstate.lazy_factory import is_global_config_type
    return is_global_config_type(t)


# Hierarchy registry - built from active form managers
# Maps: child_type -> parent_type (normalized base types)
# This is populated by ParameterFormManager when it registers
_known_hierarchy: dict = {}


def _normalize_type_for_hierarchy(t):
    """Normalize a type for hierarchy registry, but preserve lazy-global distinction.

    Normalization maps lazy types to their base types (e.g., LazyPathPlanningConfig → PathPlanningConfig).
    However, PipelineConfig → GlobalPipelineConfig is a special case: they represent DISTINCT
    hierarchy levels (pipeline overrides vs global defaults), so we must NOT collapse them.

    Rule: If normalization would produce a global type from a non-global type, keep the original.
    """
    normalized = resolve_declared_type(t)
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
        base_t = resolve_declared_type(t)
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
        target_base = resolve_declared_type(target_type)

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

    # Check 1: Is ancestor_type the lazy base of descendant_type?
    # This handles GlobalPipelineConfig → PipelineConfig relationship
    # PipelineConfig is a lazy version of GlobalPipelineConfig
    descendant_base = resolve_declared_type(descendant_type)
    if descendant_base is not descendant_type and descendant_base == ancestor_type:
        return True

    # Check 2: Normalize for comparison (handles nested lazy configs like LazyPathPlanningConfig)
    ancestor_base = resolve_declared_type(ancestor_type)
    descendant_normalized = resolve_declared_type(descendant_type)

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
    return ancestor_type in ancestors or ancestor_base in [resolve_declared_type(a) for a in ancestors]


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
    return resolve_declared_type(type_a) == resolve_declared_type(type_b)


# ============================================================================
# Context Stack Building (for UI placeholder resolution)
# ============================================================================


@contextmanager
def build_context_stack(
    object_instance: object,
    ancestor_objects_with_scopes: Sequence[tuple[str, object]] = (),
    current_scope_id: str | None = None,
    use_live: bool = True,
):
    """Resolve against one explicit baseline and the recorded ancestor layers.

    Editing a global config starts from its declared defaults, not a live object
    hidden under a masking mode. Other states start from the selected global.
    """
    from objectstate.lazy_factory import GlobalConfigBase
    editing_global = isinstance(object_instance, GlobalConfigBase)
    baseline = type(object_instance)() if editing_global else get_base_global_config(use_live=use_live)
    layers = ContextLayerStack((ContextLayer("", baseline),))
    with ExitStack() as resources:
        for variable, value in ((current_temp_global, baseline), (context_type_stack, ()), (context_layer_stack, layers)):
            resources.callback(variable.reset, variable.set(value))
        for scope_id, ancestor in ancestor_objects_with_scopes:
            if not isinstance(ancestor, GlobalConfigBase):
                resources.enter_context(config_context(ancestor, use_live_global=use_live, scope_id=scope_id))
        resources.enter_context(config_context(object_instance, use_live_global=use_live, scope_id=current_scope_id))
        yield


def merge_configs(base, overrides: Dict[str, Any]):
    """
    Merge overrides into base config, creating new immutable instance.

    A concrete ``None`` override is kept; only ``Inherit()`` requests inheritance.
    Raises whatever the config's constructor raises when the overrides are not accepted.

    Args:
        base: Base config instance (base config type)
        overrides: Dict of field_name -> value to override

    Returns:
        New config instance with overrides applied
    """
    if not base or not overrides:
        return base

    from objectstate.lazy_factory import replace_raw
    return replace_raw(base, **overrides)


def get_base_global_config(use_live: bool = True):
    """
    Get the global config a context starts from when none is active.

    This is the global config of the base config type (see ``objectstate.global_config``),
    or an instance of that type holding its declared defaults when there is none.
    Raises when no base config type is set or its defaults cannot be constructed.

    Args:
        use_live: If True (default), return LIVE config (UI sees unsaved edits).
                 If False, return SAVED config (compiler sees saved values).
    """
    from objectstate.config import get_base_config_type
    from objectstate.global_config import get_live_global_config, get_saved_global_config

    base_config_type = get_base_config_type()

    read = get_live_global_config if use_live else get_saved_global_config
    current_global = read(base_config_type)
    if current_global is not None:
        return current_global

    return base_config_type()


def get_current_temp_global():
    """
    Get current context or None.
    
    This is the primary interface for resolution functions to access
    the current context. Returns None if no context is active.
    
    Returns:
        Current merged global config or None
    """
    return current_temp_global.get(None)


# Utility functions for debugging and introspection

def get_context_info() -> Dict[str, Any]:
    current = get_current_temp_global()
    if current is None:
        return {'active': False}
    node = admit_target(current)
    declarations = node.declared_fields()
    return {
        'active': True,
        'type': type(current).__name__,
        'field_count': len(declarations),
        'non_none_fields': sum(node.read_raw(field.name).stored is not None for field in declarations),
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




def extract_all_configs(context_obj):
    """Admit an external context and return its typed configuration members."""
    return admit_target(context_obj).context_configs()








def spawn_thread_with_context(
    target,
    daemon: bool = True,
    name: str = None,
    *args,
    **kwargs,
):
    """Spawn a thread with current context propagated.

    A new thread starts with no ``config_context`` entered. This starts one with the
    layers the caller has entered (``contextvars.copy_context()``), so plain lazy
    objects read in it what they read in the caller. The global config and the
    registry are one per process and need no copying.

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
