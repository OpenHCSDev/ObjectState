"""
Generic dual-axis resolver for lazy configuration inheritance.

``resolve_with_provenance`` is the one resolution of a field in the active context,
over both the context hierarchy (X-axis) and sibling inheritance (Y-axis). It returns
the value together with the scope and type that supplied it.

The resolver is completely generic and has no application-specific dependencies.
"""

import functools
import logging
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)


class ResolvedField(NamedTuple):
    """What a field resolves to in one context, with the layer that supplied it.

    ``source_scope`` is the scope id of the supplying layer and ``source_type`` the
    config type it was read from, which is the container type or one of its bases.

    When no layer holds a value, ``value`` is the declared default (or ``None``) and
    the source names where the field lives in the context: the outermost layer holding
    the nearest type in the MRO. Both are ``None`` when no layer holds such a type.
    """

    value: Any
    source_scope: str | None
    source_type: type | None


@functools.lru_cache(maxsize=None)
def _normalize_to_base(t: type) -> type:
    """Normalize lazy type to its base type for comparison.

    LazyPartitionFilterConfig -> PartitionFilterConfig
    PartitionFilterConfig -> PartitionFilterConfig

    PERFORMANCE: Results are cached with lru_cache since type->base_type
    mappings are immutable after class creation. Import is hoisted to
    avoid per-call import overhead.
    """
    from objectstate.lazy_factory import get_base_type_for_lazy
    return get_base_type_for_lazy(t) or t


def _direct_owner_field_default(config_type: type, field_name: str) -> tuple[bool, Any]:
    """Return the default owned by config_type for field_name.

    Lazy config resolution intentionally forces inherited dataclass fields to
    None so they can inherit through context and MRO. Fields declared directly
    on the concrete owner still have their semantic class defaults on the base
    config type. Those defaults are load-bearing when no scope supplies a
    concrete value.
    """
    if not is_dataclass(config_type):
        return False, None

    field_obj = config_type.__dataclass_fields__.get(field_name)
    if field_obj is None:
        return False, None

    metadata = field_obj.metadata or {}
    if "_inherited_default" in metadata or "_inherited_default_factory" in metadata:
        return False, None

    if field_obj.default is not MISSING:
        return True, field_obj.default

    if field_obj.default_factory is not MISSING:
        return True, field_obj.default_factory()

    return False, None


def declared_default(container_type: type, field_name: str) -> tuple[Any, type | None]:
    """The value a field has when no context layer supplies one.

    In order: the default the base type declares for the field itself, the first
    concrete class attribute along the base type's MRO, then the default the field
    had before it was rebuilt to inherit (kept in the field's metadata).

    Returns the value and, when the base type declares a default for the field
    itself, that base type; otherwise ``None`` in its place.
    """
    container_base = _normalize_to_base(container_type)
    has_own_default, own_default = _direct_owner_field_default(container_base, field_name)
    own_default_type = container_base if has_own_default else None
    if own_default is not None:
        return own_default, own_default_type

    for mro_class in container_base.__mro__:
        class_value = getattr(mro_class, field_name, None)
        if class_value is not None:
            return class_value, own_default_type

    if is_dataclass(container_type):
        for field_definition in fields(container_type):
            if field_definition.name != field_name:
                continue
            metadata = field_definition.metadata
            inherited = metadata.get("_inherited_default", MISSING)
            if inherited is not MISSING:
                return inherited, own_default_type
            factory = metadata.get("_inherited_default_factory", MISSING)
            if factory is not MISSING:
                return factory(), own_default_type
    return None, own_default_type


def resolve_with_provenance(container_type: type, field_name: str) -> ResolvedField:
    """
    Resolve a field in the active context: its value and the layer that supplied it.

    This is the one resolution. Attribute access on a lazy config takes ``.value``
    from it; ``ObjectState`` takes the value and the source together.

    The answer is kept on the active layer stack, so it lives exactly as long as the
    context it was computed from.

    Args:
        container_type: The type containing the field (e.g., LazyPathPlanningConfig)
        field_name: Name of the field to resolve (e.g., "partition_filter")

    Raises:
        NoActiveContextError: no ``config_context`` is active.
    """
    from objectstate.context_manager import NoActiveContextError, context_layer_stack

    stack = context_layer_stack.get()
    if not stack.layers:
        raise NoActiveContextError(
            f"Cannot resolve {container_type.__name__}.{field_name}: "
            "no config context is active."
        )
    return resolve_in_stack(stack, container_type, field_name)


def resolve_in_stack(stack, container_type: type, field_name: str) -> ResolvedField:
    """``resolve_with_provenance`` for a layer stack the caller already holds."""
    key = (container_type, field_name)
    resolved = stack.resolved_fields.get(key)
    if resolved is None:
        resolved = stack.resolved_fields[key] = _resolve_in_layers(
            stack.layers, container_type, field_name
        )
    return resolved


def _resolve_in_layers(layers: tuple, container_type: type, field_name: str) -> ResolvedField:
    """Resolve class first: the MRO is the outer loop, the layers the inner one.

    For each class in the container type's MRO, most specific first, every layer is
    asked from the innermost scope to the outermost; the first value that is not
    ``None`` wins. ``None`` in an inner layer means "inherit", so a less specific
    class is tried only after every layer was asked for the more specific one.
    A layer that masks the layers outside it ends the walk outward.

    The order is stated with an example in ``docs/context_system.rst`` under
    "Precedence Order"; this function is its implementation.
    """
    container_base = _normalize_to_base(container_type)

    visible_layers = []
    for layer in reversed(layers):
        visible_layers.append(layer)
        if layer.masks_outer_layers:
            break

    # Where the field lives when every layer leaves it None: the outermost layer
    # holding the first MRO type that any layer holds.
    unset_scope: str | None = None
    unset_type: type | None = None
    unset_found = False

    for mro_class in container_base.__mro__:
        if not is_dataclass(mro_class):
            continue
        mro_type = _normalize_to_base(mro_class)
        outermost_scope: str | None = None
        held_by_a_layer = False

        for layer in visible_layers:
            config_instance = layer.configs.get(mro_type)
            if config_instance is None:
                continue
            held_by_a_layer = True
            outermost_scope = layer.scope_id
            try:
                value = object.__getattribute__(config_instance, field_name)
            except AttributeError:
                continue
            if value is not None:
                return ResolvedField(value, layer.scope_id, mro_type)

        if held_by_a_layer and not unset_found:
            unset_found = True
            unset_scope = outermost_scope
            unset_type = mro_type

    default_value, own_default_type = declared_default(container_type, field_name)
    return ResolvedField(default_value, unset_scope, own_default_type or unset_type)


def get_field_provenance(
    container_type: type, field_name: str
) -> tuple[str | None, type | None]:
    """
    Find which scope AND type provided the concrete value for a field.

    The scope and type of ``resolve_with_provenance()``, without the value.

    Args:
        container_type: The type containing the field (e.g., LazyPathPlanningConfig)
        field_name: Name of the field to find provenance for (e.g., "partition_filter")

    Returns:
        (source_scope_id, source_type): The scope_id and type that provided the value.
        source_type may differ from container_type due to MRO inheritance.
        See ``ResolvedField`` for what they name when no layer has a concrete value.
    """
    _, source_scope, source_type = resolve_with_provenance(container_type, field_name)
    return source_scope, source_type
