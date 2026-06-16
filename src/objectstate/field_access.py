"""Authoritative field access helpers for dataclass-backed ObjectState values."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from types import GetSetDescriptorType, MemberDescriptorType
from typing import Iterator


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

    def child(self, field_name: str) -> "DottedFieldPath":
        if self.value == "":
            return DottedFieldPath(field_name)
        return DottedFieldPath(f"{self.value}.{field_name}")


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
                raise FieldAccessError(
                    f"{type(instance).__name__}.{field_name} is not stored on the instance."
                )
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
