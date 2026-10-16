"""Stored field meaning, independent of the domain value (including None)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class FieldValue(ABC):
    """Interpret a stored value once; consumers invoke its field operations."""

    __slots__ = ()
    inherited = False
    has_value = False

    @classmethod
    def of(cls, value: Any) -> FieldValue:
        return value if isinstance(value, cls) else Value(value)

    @staticmethod
    def is_inherited(value: Any) -> bool:
        return isinstance(value, FieldValue) and value.inherited

    @abstractmethod
    def resolve(self, inherited: Callable[[], Any]) -> Any:
        """Read the effective value, requesting inheritance only when declared."""

    @abstractmethod
    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        """Apply this stored value over a base without interpreting None."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self))

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def source(self, context):
        from pycodify import SourceFragment, imported_name
        reference = imported_name(type(self).__module__, type(self).__qualname__, context)
        return SourceFragment(f"{reference.code}()", reference.imports)


class Inherit(FieldValue):
    """Continue the existing context/MRO lookup instead of supplying a value."""

    __slots__ = ()
    inherited = True

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return inherited()

    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        return base


class Unset(FieldValue):
    """No value is available. This is neither None nor an inheritance request."""

    __slots__ = ()

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return self

    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        return self


class Value(FieldValue):
    """A concrete domain value, including an explicitly stored None."""

    __slots__ = ('value',)
    has_value = True

    def __init__(self, value: Any):
        self.value = value

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return self.value

    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        return merge(base, self.value)

    def __eq__(self, other: object) -> bool:
        from objectstate.value_semantics import semantic_values_equal
        return isinstance(other, Value) and semantic_values_equal(self.value, other.value)

    __hash__ = None

    def __deepcopy__(self, memo):
        from copy import deepcopy
        return Value(deepcopy(self.value, memo))

    def source(self, context):
        from pycodify import to_source
        return to_source(self.value, context)
