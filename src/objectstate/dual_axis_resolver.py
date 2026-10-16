"""
Generic dual-axis resolver for lazy configuration inheritance.

``resolve_with_provenance`` is the one resolution of a field in the active context,
over both the context hierarchy (X-axis) and sibling inheritance (Y-axis). It returns
the value together with the scope and type that supplied it.

The resolver is completely generic and has no application-specific dependencies.
"""

import functools
import logging
from typing import Any, NamedTuple

from objectstate.field_access import DataclassFieldAccess
from objectstate.field_value import FieldValue, Unset
from objectstate.declarations import ValueDeclaration
from python_introspect import resolve_declared_type

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


def declared_default(container_type: type, field_name: str) -> tuple[Any, type | None]:
    """Defaults come from declarations, never slot descriptors or guessed attributes."""
    base = ValueDeclaration.of(resolve_declared_type(container_type))
    own = base.own_default(field_name)
    own_type = base.declaring_type if own.available() else None
    if own.available():
        return own.stored, own_type
    for declaration in base.configuration_mro(field_name):
        value = declaration.own_default(field_name)
        if value.available():
            return value.stored, own_type
    return ValueDeclaration.of(container_type).inherited_default(field_name).stored, own_type


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
    container_base = resolve_declared_type(container_type)

    visible_layers = tuple(reversed(layers))

    # Where the field lives when every layer leaves it None: the outermost layer
    # holding the first MRO type that any layer holds.
    unset_scope: str | None = None
    unset_type: type | None = None
    unset_found = False

    for declaration in ValueDeclaration.of(container_base).configuration_mro(field_name):
        mro_type = resolve_declared_type(declaration.declaring_type)
        outermost_scope: str | None = None
        held_by_a_layer = False

        for layer in visible_layers:
            config_instance = layer.configs.get(mro_type)
            if config_instance is None:
                continue
            value = config_instance.read_raw(field_name)
            held_by_a_layer = True
            outermost_scope = layer.scope_id
            if value.available():
                return ResolvedField(value.stored, layer.scope_id, mro_type)

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
