"""Structural semantic projection for values owned by one ObjectState field."""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import Enum
from typing import Generic, TypeVar

from objectstate.field_access import DataclassFieldAccess, DottedFieldPath


SubfieldValueT = TypeVar("SubfieldValueT")


@dataclass(frozen=True, slots=True)
class MissingValue:
    """Nominal sentinel for an absent structural leaf."""


MISSING = MissingValue()


class StructuralSegmentKind(str, Enum):
    """Closed segment kinds for structural value paths."""

    DATACLASS_FIELD = "dataclass_field"
    SEQUENCE_INDEX = "sequence_index"
    MAPPING_KEY = "mapping_key"


@dataclass(frozen=True, slots=True)
class StructuralPathSegment:
    """One typed segment inside a structural value path."""

    kind: StructuralSegmentKind
    value: str | int


@dataclass(frozen=True, slots=True)
class StructuralValuePath:
    """Typed relative path from an ObjectState owner field into its value."""

    segments: tuple[StructuralPathSegment, ...] = ()

    def child_field(self, name: str) -> "StructuralValuePath":
        return StructuralValuePath(
            self.segments
            + (
                StructuralPathSegment(
                    StructuralSegmentKind.DATACLASS_FIELD,
                    name,
                ),
            )
        )

    def child_index(self, index: int) -> "StructuralValuePath":
        return StructuralValuePath(
            self.segments
            + (
                StructuralPathSegment(
                    StructuralSegmentKind.SEQUENCE_INDEX,
                    index,
                ),
            )
        )

    def display_suffix(self) -> str:
        suffix = ""
        for segment in self.segments:
            if segment.kind is StructuralSegmentKind.DATACLASS_FIELD:
                suffix += f".{segment.value}"
            elif segment.kind is StructuralSegmentKind.SEQUENCE_INDEX:
                suffix += f"[{segment.value}]"
            elif segment.kind is StructuralSegmentKind.MAPPING_KEY:
                suffix += f"[{segment.value!r}]"
        return suffix

    @classmethod
    def from_display_suffix(cls, suffix: str) -> "StructuralValuePath":
        """Parse a suffix emitted by :meth:`display_suffix`."""

        if not suffix:
            return cls()

        index = 0
        path = cls()
        while index < len(suffix):
            char = suffix[index]
            if char == ".":
                next_index = _next_structural_delimiter(suffix, index + 1)
                field_name = suffix[index + 1 : next_index]
                if not field_name:
                    raise ValueError(f"Empty structural field segment in {suffix!r}.")
                path = path.child_field(field_name)
                index = next_index
                continue
            if char == "[":
                close_index = suffix.find("]", index + 1)
                if close_index < 0:
                    raise ValueError(f"Unclosed structural index segment in {suffix!r}.")
                value = suffix[index + 1 : close_index]
                if not value.isdecimal():
                    raise ValueError(
                        "Only sequence-index structural suffixes are supported; "
                        f"got {value!r} in {suffix!r}."
                    )
                path = path.child_index(int(value))
                index = close_index + 1
                continue
            raise ValueError(
                f"Structural suffix must use '.' or '[' segments; got {suffix!r}."
            )
        return path


@dataclass(frozen=True, slots=True)
class StructuralFieldPath:
    """A writable ObjectState owner field plus a projected structural child path."""

    owner_field_path: DottedFieldPath
    relative_path: StructuralValuePath

    @classmethod
    def from_display_path(cls, field_path: str) -> "StructuralFieldPath | None":
        """Parse a display path emitted from an owner path plus structural suffix."""

        first_sequence_index = field_path.find("[")
        if first_sequence_index < 0:
            return None

        owner_value = field_path[:first_sequence_index]
        suffix_value = field_path[first_sequence_index:]
        if not owner_value:
            raise ValueError(
                f"Structural field path {field_path!r} has no owner field path."
            )
        if "." in suffix_value:
            first_relative_field = suffix_value.split(".", 1)[1]
            if not first_relative_field:
                raise ValueError(
                    f"Structural field path {field_path!r} has an empty relative field."
                )

        return cls(
            owner_field_path=DottedFieldPath(owner_value),
            relative_path=StructuralValuePath.from_display_suffix(suffix_value),
        )


def _next_structural_delimiter(text: str, start: int) -> int:
    dot_index = text.find(".", start)
    bracket_index = text.find("[", start)
    candidates = tuple(
        index for index in (dot_index, bracket_index) if index >= 0
    )
    return min(candidates) if candidates else len(text)


@dataclass(frozen=True, slots=True)
class ObjectStateSubfieldSemantic(Generic[SubfieldValueT]):
    """Semantic state for one structural leaf under an ObjectState owner field."""

    owner_field_path: DottedFieldPath
    relative_path: StructuralValuePath
    display_path: str
    value_type_name: str | None

    raw_value: SubfieldValueT | MissingValue
    resolved_value: SubfieldValueT | MissingValue
    saved_resolved_value: SubfieldValueT | MissingValue
    signature_default_value: SubfieldValueT | MissingValue

    raw_present: bool
    resolved_present: bool
    saved_resolved_present: bool
    signature_default_present: bool

    dirty: bool
    signature_diff: bool
    inherited_value: bool
    semantic_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObjectStateSubfieldSemanticIndex:
    """Semantic projection for all structural leaves under one owner field."""

    owner_field_path: DottedFieldPath
    owner_dirty: bool
    owner_signature_diff: bool
    owner_inherited_value: bool
    leaves: tuple[ObjectStateSubfieldSemantic, ...]

    def leaf_for(
        self,
        relative_path: StructuralValuePath,
    ) -> ObjectStateSubfieldSemantic | None:
        for leaf in self.leaves:
            if leaf.relative_path == relative_path:
                return leaf
        return None


def build_subfield_semantic_index(
    *,
    owner_field_path: DottedFieldPath,
    raw_value,
    resolved_value,
    saved_resolved_value,
    signature_default_value,
    owner_dirty: bool,
    owner_signature_diff: bool,
) -> ObjectStateSubfieldSemanticIndex:
    """Build structural leaf semantics from ObjectState-owned values."""

    raw_leaves = _leaf_values(raw_value)
    resolved_leaves = _leaf_values(resolved_value)
    saved_leaves = _leaf_values(saved_resolved_value)
    default_leaves = _leaf_values(signature_default_value)

    ordered_paths = _ordered_paths(raw_leaves, resolved_leaves, saved_leaves, default_leaves)
    if any(path.segments for path in ordered_paths):
        ordered_paths = tuple(path for path in ordered_paths if path.segments)

    leaves = tuple(
        _build_leaf(
            owner_field_path=owner_field_path,
            relative_path=relative_path,
            raw_value=raw_leaves.get(relative_path, MISSING),
            resolved_value=resolved_leaves.get(relative_path, MISSING),
            saved_resolved_value=saved_leaves.get(relative_path, MISSING),
            signature_default_value=default_leaves.get(relative_path, MISSING),
        )
        for relative_path in ordered_paths
    )

    return ObjectStateSubfieldSemanticIndex(
        owner_field_path=owner_field_path,
        owner_dirty=owner_dirty,
        owner_signature_diff=owner_signature_diff,
        owner_inherited_value=raw_value is None and resolved_value is not None,
        leaves=leaves,
    )


def changed_structural_leaf_paths(
    *,
    owner_field_path: DottedFieldPath,
    old_value,
    new_value,
) -> tuple[str, ...]:
    """Return display paths for structural leaves whose values changed."""

    old_leaves = _leaf_values(old_value)
    new_leaves = _leaf_values(new_value)
    changed_paths = tuple(
        relative_path
        for relative_path in _ordered_paths(old_leaves, new_leaves)
        if relative_path.segments
        and old_leaves.get(relative_path, MISSING)
        != new_leaves.get(relative_path, MISSING)
    )
    return tuple(
        f"{owner_field_path.value}{relative_path.display_suffix()}"
        for relative_path in changed_paths
    )


def _build_leaf(
    *,
    owner_field_path: DottedFieldPath,
    relative_path: StructuralValuePath,
    raw_value,
    resolved_value,
    saved_resolved_value,
    signature_default_value,
) -> ObjectStateSubfieldSemantic:
    raw_present = raw_value is not MISSING
    resolved_present = resolved_value is not MISSING
    saved_resolved_present = saved_resolved_value is not MISSING
    signature_default_present = signature_default_value is not MISSING
    dirty = resolved_value != saved_resolved_value
    signature_diff = raw_value != signature_default_value
    inherited_value = not raw_present and resolved_present
    display_path = f"{owner_field_path.value}{relative_path.display_suffix()}"
    markers: list[str] = []
    if dirty:
        markers.append("*")
    if signature_diff or inherited_value:
        markers.append("_")
    value_type = resolved_value if resolved_present else raw_value
    value_type_name = None if value_type is MISSING else type(value_type).__qualname__

    return ObjectStateSubfieldSemantic(
        owner_field_path=owner_field_path,
        relative_path=relative_path,
        display_path=display_path,
        value_type_name=value_type_name,
        raw_value=raw_value,
        resolved_value=resolved_value,
        saved_resolved_value=saved_resolved_value,
        signature_default_value=signature_default_value,
        raw_present=raw_present,
        resolved_present=resolved_present,
        saved_resolved_present=saved_resolved_present,
        signature_default_present=signature_default_present,
        dirty=dirty,
        signature_diff=signature_diff,
        inherited_value=inherited_value,
        semantic_markers=tuple(markers),
    )


def _leaf_values(value) -> dict:
    if value is MISSING:
        return {}
    return dict(_iter_leaf_values(value, StructuralValuePath()))


def _iter_leaf_values(value, path: StructuralValuePath):
    if _is_dataclass_instance(value):
        for dataclass_field in dataclass_fields(type(value)):
            child_path = path.child_field(dataclass_field.name)
            child_value = DataclassFieldAccess.raw_value(value, dataclass_field.name)
            yield from _iter_leaf_values(child_value, child_path)
        return

    if isinstance(value, (tuple, list)):
        for index, child_value in enumerate(value):
            yield from _iter_leaf_values(child_value, path.child_index(index))
        return

    yield path, value


def _ordered_paths(*leaf_sets: dict) -> tuple[StructuralValuePath, ...]:
    ordered: list[StructuralValuePath] = []
    seen: set[StructuralValuePath] = set()
    for leaves in leaf_sets:
        for path in leaves:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return tuple(ordered)


def _is_dataclass_instance(value) -> bool:
    return is_dataclass(value) and not isinstance(value, type)
