"""Read-only inspection of registered ObjectStates and their fields."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from objectstate.field_access import DottedFieldPath
from objectstate.object_state import ObjectState
from objectstate.object_state_registry import ObjectStateRegistry

logger = logging.getLogger(__name__)

DIRTY_MARKER = "*"
"""Marks a field (or a group of fields) whose value differs from the saved value."""

SIGNATURE_DIFF_MARKER = "_"
"""Marks a field whose raw value differs from its declared signature default."""


def field_markers(*, dirty: bool, signature_diff: bool) -> tuple[str, ...]:
    """The markers views prefix to a field, or to a group of fields, in this order."""

    return tuple(
        marker
        for marker, present in ((DIRTY_MARKER, dirty), (SIGNATURE_DIFF_MARKER, signature_diff))
        if present
    )


def state_markers(state: ObjectState) -> tuple[str, ...]:
    """The markers of a whole ObjectState: any dirty field, any signature difference."""

    return field_markers(
        dirty=bool(state.dirty_fields),
        signature_diff=bool(state.signature_diff_fields),
    )


def type_name(value: object) -> str:
    return "None" if value is None else type(value).__name__


def type_qualname(value_type: type | Callable[..., object]) -> str:
    return f"{value_type.__module__}.{value_type.__qualname__}"


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """The ancestor scope and declaring type a field's inherited value comes from."""

    source_scope_id: str | None
    source_type: type
    field_name: str

    @property
    def source_field_path(self) -> str | None:
        """The field's path in the source scope's own state, if that scope is registered."""

        source_state = ObjectStateRegistry.get_by_scope(self.source_scope_id)
        if source_state is None:
            return None
        return source_state.project_ui_visible_field_path(self.source_type, self.field_name)


@dataclass(frozen=True, slots=True)
class FieldInspection:
    """One field of one ObjectState: raw and resolved value, edit state and provenance."""

    state: ObjectState
    field_path: str
    raw_value: object
    resolved_value: object
    resolved_value_available: bool
    provenance: FieldProvenance | None

    @classmethod
    def of(cls, state: ObjectState, field_path: str):
        """Inspect ``field_path``; a value that fails to resolve is reported unavailable."""

        resolved_value = None
        resolved_value_available = False
        try:
            resolved_value = state.get_resolved_value(field_path)
            resolved_value_available = True
        except Exception:
            logger.debug(
                "Failed to resolve ObjectState field %s on scope %r.",
                field_path,
                state.scope_id,
                exc_info=True,
            )
        provenance = None
        match state.get_provenance(field_path):
            case (source_scope_id, source_type) if source_type is not None:
                provenance = FieldProvenance(
                    source_scope_id=source_scope_id,
                    source_type=source_type,
                    field_name=DottedFieldPath(field_path).field_name,
                )
        return cls(
            state=state,
            field_path=field_path,
            raw_value=state.parameters[field_path],
            resolved_value=resolved_value,
            resolved_value_available=resolved_value_available,
            provenance=provenance,
        )

    @property
    def dirty(self) -> bool:
        return self.field_path in self.state.dirty_fields

    @property
    def signature_diff(self) -> bool:
        return self.field_path in self.state.signature_diff_fields

    @property
    def last_changed(self) -> bool:
        return self.field_path == self.state.last_changed_field

    @property
    def raw_value_is_none(self) -> bool:
        return self.raw_value is None

    @property
    def resolved_value_is_none(self) -> bool:
        return self.resolved_value_available and self.resolved_value is None

    @property
    def inherited_value(self) -> bool:
        """The field holds no value of its own and inherits a resolved one."""

        return self.raw_value is None and self.resolved_value_available and (
            self.resolved_value is not None
        )

    @property
    def semantic_markers(self) -> tuple[str, ...]:
        return field_markers(dirty=self.dirty, signature_diff=self.signature_diff)

    @property
    def field_name(self) -> str:
        return DottedFieldPath(self.field_path).field_name

    @property
    def container_path(self) -> str:
        return DottedFieldPath(self.field_path).parent.value

    @property
    def raw_value_type(self) -> str:
        return type_name(self.raw_value)

    @property
    def resolved_value_type(self) -> str | None:
        return type_name(self.resolved_value) if self.resolved_value_available else None

    @property
    def declaring_type(self) -> str:
        """Qualified name of the dataclass that declares this field."""

        return type_qualname(self.state.type_for_path(self.field_path))
