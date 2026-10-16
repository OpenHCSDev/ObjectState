"""Read-only inspection of registered ObjectStates and their fields."""

from __future__ import annotations
from objectstate.field_value import FieldValue
from collections.abc import Callable
from dataclasses import dataclass

from objectstate.object_state import FieldProxy, ObjectState
from objectstate.object_state_registry import ObjectStateRegistry

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

    field: FieldProxy
    raw: FieldValue
    resolved: FieldValue
    provenance: FieldProvenance | None

    @classmethod
    def of(cls, field):
        """Capture one admitted field, never look up a caller-spelled path."""
        resolved = field.resolved_member
        provenance = None
        match field.provenance:
            case (source_scope_id, source_type) if source_type is not None:
                provenance = FieldProvenance(
                    source_scope_id=source_scope_id,
                    source_type=source_type,
                    field_name=field.name,
                )
        return cls(
            field=field,
            raw=field.raw_member,
            resolved=resolved,
            provenance=provenance,
        )

    @property
    def dirty(self) -> bool:
        return self.field.dirty

    @property
    def signature_diff(self) -> bool:
        return self.field.signature_diff

    @property
    def last_changed(self) -> bool:
        return self.field_path == self.field.state.last_changed_field

    @property
    def raw_value_is_inherited(self) -> bool:
        return self.raw.inherits()

    @property
    def inherited_value(self) -> bool:
        """The field holds no value of its own and inherits a resolved one."""

        return self.raw.inherited_from(self.resolved)

    @property
    def semantic_markers(self) -> tuple[str, ...]:
        return field_markers(dirty=self.dirty, signature_diff=self.signature_diff)

    @property
    def field_path(self) -> str:
        """External address spelling is projected through the existing codec."""
        return self.field.address.value

    @property
    def field_name(self) -> str:
        return self.field.name

    @property
    def container_path(self) -> str:
        return self.field.address.parent.value

    @property
    def raw_value_type(self) -> str:
        return self.raw.project(type_name)

    @property
    def resolved_value_type(self) -> str | None:
        return self.resolved.project(type_name)

    @property
    def declaring_type(self) -> str:
        """Qualified name of the dataclass that declares this field."""

        return type_qualname(self.field.declaring_type)
