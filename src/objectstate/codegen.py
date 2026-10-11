"""Python source for lazy dataclasses, through pycodify.

Importing this module registers :class:`LazyDataclassFormatter`. A lazy
dataclass is written from its raw field values, never its resolved ones: a
``None`` field inherits from context and stays ``None`` in the source.

Clean mode writes a field when it was passed to the constructor or holds a
concrete value; an inherited ``None`` is omitted, and so is a nested lazy
dataclass that carries nothing. Full mode writes every field.
"""

from __future__ import annotations

from dataclasses import fields

from pycodify import (
    FormatContext,
    SourceFormatter,
    SourceFragment,
    imported_name,
    to_source,
)

from objectstate.field_access import DataclassFieldAccess
from objectstate.lazy_factory import LazyDataclass


def _set_field_names(value: LazyDataclass) -> frozenset[str]:
    return frozenset(object.__getattribute__(value, "_explicitly_set_fields"))


def lazy_dataclass_carries_values(value: LazyDataclass) -> bool:
    """Whether a lazy dataclass has a constructor-set field or a concrete value."""

    return bool(_set_field_names(value)) or any(
        DataclassFieldAccess.raw_value(value, field.name) is not None
        for field in fields(value)
    )


def lazy_raw_values_equal(left: LazyDataclass, right: LazyDataclass) -> bool:
    """Whether two lazy dataclasses have the same type and raw field values."""

    if type(left) is not type(right):
        return False
    for field in fields(left):
        left_value = DataclassFieldAccess.raw_value(left, field.name)
        right_value = DataclassFieldAccess.raw_value(right, field.name)
        if isinstance(left_value, LazyDataclass) and isinstance(right_value, LazyDataclass):
            if not lazy_raw_values_equal(left_value, right_value):
                return False
        elif left_value != right_value:
            return False
    return True


def field_needs_source(current: object, default: object, context: FormatContext) -> bool:
    """Whether an owner's field holding ``current`` must be written.

    For owners (such as a step) that format their own constructor fields and
    hold lazy dataclasses among them. Full mode writes every field; clean mode
    writes a lazy dataclass that carries values different from the default,
    and any other value that differs from the default.
    """

    if not context.clean_mode:
        return True
    if isinstance(current, LazyDataclass):
        if not lazy_dataclass_carries_values(current):
            return False
        return not (
            isinstance(default, LazyDataclass) and lazy_raw_values_equal(current, default)
        )
    return current != default


def _clean_field_needs_source(value: LazyDataclass, name: str, current: object) -> bool:
    if current is None:
        return False
    if name in _set_field_names(value):
        return True
    if isinstance(current, LazyDataclass):
        return lazy_dataclass_carries_values(current)
    return True


class LazyDataclassFormatter(SourceFormatter):
    priority = 36

    def can_format(self, value: object) -> bool:
        return isinstance(value, LazyDataclass)

    def format(self, value: LazyDataclass, context: FormatContext) -> SourceFragment:
        lazy_type = type(value)
        class_ref = imported_name(lazy_type.__module__, lazy_type.__qualname__, context)
        imports = set(class_ref.imports)
        field_ctx = context.indented()
        lines = []
        for field in fields(value):
            if not field.init:
                continue
            current = DataclassFieldAccess.raw_value(value, field.name)
            if context.clean_mode and not _clean_field_needs_source(
                value, field.name, current
            ):
                continue
            fragment = to_source(current, field_ctx)
            imports |= fragment.imports
            lines.append(f"{field.name}={fragment.code}")

        if not lines:
            return SourceFragment(f"{class_ref.code}()", frozenset(imports))
        inner = f",\n{field_ctx.indent_str}".join(lines)
        code = f"{class_ref.code}(\n{field_ctx.indent_str}{inner}\n{context.indent_str})"
        return SourceFragment(code, frozenset(imports))
