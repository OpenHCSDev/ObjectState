"""Authoritative field access helpers for dataclass-backed ObjectState values."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import GetSetDescriptorType, MemberDescriptorType
from typing import Iterable, Iterator


class FieldAccessError(AttributeError):
    """Raised when a requested dataclass field path cannot be resolved."""


@dataclass(frozen=True, slots=True)
class DottedFieldPath:
    """Validated dotted dataclass field path."""

    value: str

    @property
    def parts(self) -> tuple[str, ...]:
        if self.value == "":
            return ()
        return tuple(part for part in self.value.split(".") if part)

    @property
    def field_name(self) -> str:
        """Return the declared leaf name represented by this path."""

        return self.parts[-1] if self.parts else ""

    def child(self, field_name: str) -> "DottedFieldPath":
        if self.value == "":
            return DottedFieldPath(field_name)
        return DottedFieldPath(f"{self.value}.{field_name}")

    def contains_path(self, candidate: str | "DottedFieldPath") -> bool:
        """Return whether this field path owns a dotted or structural display path."""

        candidate_value = candidate.value if isinstance(candidate, DottedFieldPath) else candidate
        return (
            candidate_value == self.value
            or candidate_value.startswith(f"{self.value}.")
            or candidate_value.startswith(f"{self.value}[")
        )

    def contains_any(self, candidates: Iterable[str | "DottedFieldPath"]) -> bool:
        """Return whether this field path owns any candidate display path."""

        return any(self.contains_path(candidate) for candidate in candidates)

    def intersects_path(self, other: str | "DottedFieldPath") -> bool:
        """Return whether this path and another path overlap in either direction."""

        other_path = other if isinstance(other, DottedFieldPath) else DottedFieldPath(other)
        return self.contains_path(other_path) or other_path.contains_path(self)

    def direct_child_name(self, candidate: str | "DottedFieldPath") -> str | None:
        """Return the direct dotted child field owned by this path, when one exists."""

        candidate_value = candidate.value if isinstance(candidate, DottedFieldPath) else candidate
        if candidate_value == self.value or not self.contains_path(candidate_value):
            return None
        remainder = candidate_value[len(self.value):]
        if not remainder.startswith("."):
            return None
        child_remainder = remainder[1:]
        child_name = child_remainder.split(".", 1)[0].split("[", 1)[0]
        return child_name or None


class DataclassFieldAccess:
    """Single authority for raw dataclass reads and dotted field traversal."""

    _SLOT_DESCRIPTOR_TYPES = (MemberDescriptorType, GetSetDescriptorType)

    @staticmethod
    def field_names(instance_or_type) -> frozenset[str]:
        dataclass_type = instance_or_type if isinstance(instance_or_type, type) else type(instance_or_type)
        if not is_dataclass(dataclass_type):
            raise TypeError(
                "DataclassFieldAccess requires a dataclass instance or type; "
                f"got {dataclass_type!r}."
            )
        return frozenset(field.name for field in fields(dataclass_type))

    @staticmethod
    def init_field_names(instance_or_type) -> tuple[str, ...]:
        dataclass_type = instance_or_type if isinstance(instance_or_type, type) else type(instance_or_type)
        if not is_dataclass(dataclass_type):
            raise TypeError(
                "DataclassFieldAccess requires a dataclass instance or type; "
                f"got {dataclass_type!r}."
            )
        return tuple(field.name for field in fields(dataclass_type) if field.init)

    @classmethod
    def has_field(cls, instance_or_type, field_name: str) -> bool:
        return field_name in cls.field_names(instance_or_type)

    @classmethod
    def raw_value(cls, instance, field_name: str):
        if instance is None:
            raise FieldAccessError(f"Cannot read field {field_name!r} from None.")
        if not cls.has_field(instance, field_name):
            raise FieldAccessError(
                f"{type(instance).__name__} has no dataclass field {field_name!r}."
            )
        if cls._has_instance_dict(type(instance)):
            storage = vars(instance)
            if field_name not in storage:
                return cls._slot_field_value(instance, field_name)
            return storage[field_name]

        return cls._slot_field_value(instance, field_name)

    @staticmethod
    def _has_instance_dict(instance_type: type) -> bool:
        return instance_type.__dictoffset__ != 0

    @classmethod
    def _slot_field_value(cls, instance, field_name: str):
        descriptor = cls._slot_descriptor(type(instance), field_name)
        return descriptor.__get__(instance, type(instance))

    @classmethod
    def _slot_descriptor(cls, instance_type: type, field_name: str):
        for owner in instance_type.__mro__:
            descriptor = vars(owner).get(field_name)
            if isinstance(descriptor, cls._SLOT_DESCRIPTOR_TYPES):
                return descriptor

        raise FieldAccessError(
            f"{instance_type.__name__}.{field_name} is not stored on the instance."
        )

    @classmethod
    def raw_path(cls, root, field_path: str | DottedFieldPath):
        if isinstance(field_path, DottedFieldPath):
            path = field_path
        else:
            path = DottedFieldPath(field_path)

        current = root
        for part in path.parts:
            current = cls.raw_value(current, part)
        return current

    @classmethod
    def raw_items(cls, instance, field_names: Iterator[str]):
        for field_name in field_names:
            if cls.has_field(instance, field_name):
                yield field_name, cls.raw_value(instance, field_name)

    @classmethod
    def raw_init_values(cls, instance, constructor_type: type | None = None) -> dict[str, object]:
        """Return raw values for dataclass fields accepted by a constructor."""

        field_owner = constructor_type or type(instance)
        return {
            field_name: cls.raw_value(instance, field_name)
            for field_name in cls.init_field_names(field_owner)
        }
