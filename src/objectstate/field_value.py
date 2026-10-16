"""Stored field meaning, independent of the domain value (including None)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(eq=False, repr=False)
class FieldValue(ABC):
    """Interpret a stored value once; consumers invoke its field operations."""

    __slots__ = ()

    @classmethod
    def of(cls, value: Any) -> FieldValue:
        return value if isinstance(value, cls) else Value(value)

    @staticmethod
    def is_inherited(value: Any) -> bool:
        return FieldValue.of(value).inherits()

    def available(self) -> bool:
        """Whether this member supplies domain data, including literal None."""
        return False

    def inherits(self) -> bool:
        return False

    def inherited_from(self, resolved: FieldValue) -> bool:
        return False

    def present_to(self, display) -> None:
        """Let a view paint this directive without inventing a datum."""
        display.present_directive(self)

    def map(self, convert: Callable[[Any], Any]) -> Any:
        """Convert domain data without converting an inheritance/absence directive."""
        return self

    def project(self, convert: Callable[[Any], Any]) -> Any:
        """Pass the datum or directive itself to the view, without context lookup."""
        return convert(self.resolve(lambda: self))

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


@dataclass(eq=False, repr=False)
class Inherit(FieldValue):
    """Continue the existing context/MRO lookup instead of supplying a value."""

    __slots__ = ()

    def inherits(self) -> bool:
        return True

    def inherited_from(self, resolved: FieldValue) -> bool:
        return resolved.available()

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return inherited()

    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        return base


@dataclass(eq=False, repr=False)
class Unset(FieldValue):
    """No value is available. This is neither None nor an inheritance request."""

    __slots__ = ()

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return self

    def overlay(self, base: Any, merge: Callable[[Any, Any], Any]) -> Any:
        return self


@dataclass(eq=False, repr=False)
class Value(FieldValue):
    """A concrete domain value, including an explicitly stored None."""

    __slots__ = ('value',)
    value: Any

    def __init__(self, value: Any):
        self.value = value

    def available(self) -> bool:
        return True

    def present_to(self, display) -> None:
        display.present_value(self.value)

    def resolve(self, inherited: Callable[[], Any]) -> Any:
        return self.value

    def map(self, convert: Callable[[Any], Any]) -> Any:
        return convert(self.value)

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
