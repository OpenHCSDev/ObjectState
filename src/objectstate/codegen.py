"""Python source for lazily resolved dataclasses, through pycodify.

Importing this module registers the field formatters. Both write raw field values,
never resolved ones. ``None`` remains literal data; ``Inherit`` and ``Unset``
retain their distinct meanings in the source.

- :class:`LazyResolutionFormatter` (any :class:`LazyResolutionDataclass`):
  clean mode writes the fields whose raw value differs from the field default.
- :class:`LazyDataclassFormatter` (factory-made :class:`LazyDataclass`): clean
  mode writes a field when it was passed to the constructor or holds a concrete
  value. Inherited fields may be omitted; an empty nested configuration is
  still an object, not a literal None.

Full mode writes every field.
"""

from __future__ import annotations

from dataclasses import MISSING, Field, fields

from pycodify import (
    FormatContext,
    SourceFormatter,
    SourceFragment,
    imported_name,
    to_source,
)

from objectstate.field_access import DataclassFieldAccess
from objectstate.field_value import FieldValue
from objectstate.lazy_factory import LazyDataclass, LazyResolutionDataclass


def _set_field_names(value: LazyDataclass) -> frozenset[str]:
    return frozenset(object.__getattribute__(value, "_explicitly_set_fields"))




def raw_values_equal(left: object, right: object) -> bool:
    """Whether two values are equal, comparing dataclasses by raw field values."""

    if DataclassFieldAccess.is_container(left) and DataclassFieldAccess.is_container(right):
        if type(left) is not type(right):
            return False
        return all(
            raw_values_equal(
                DataclassFieldAccess.raw_value(left, field.name),
                DataclassFieldAccess.raw_value(right, field.name),
            )
            for field in fields(left)
            if field.init
        )
    return left == right


def field_needs_source(current: object, default: object, context: FormatContext) -> bool:
    """Whether an owner's field holding ``current`` must be written.

    For owners (such as a step) that format their own constructor fields and
    hold lazy dataclasses among them. Full mode writes every field; clean mode
    writes a lazy dataclass that carries values different from the default,
    and any other value that differs from the default.
    """

    if not context.clean_mode:
        return True
    return not raw_values_equal(current, default)


def _field_default(field: Field) -> object:
    if field.default is not MISSING:
        return field.default
    if field.default_factory is not MISSING:
        return field.default_factory()
    return MISSING


class LazyResolutionFormatter(SourceFormatter):
    priority = 36
    formats: type = LazyResolutionDataclass

    def can_format(self, value: object) -> bool:
        return isinstance(value, self.formats)

    def clean_field_needs_source(self, value: object, field: Field, current: object) -> bool:
        return not raw_values_equal(current, _field_default(field))

    def format(self, value: object, context: FormatContext) -> SourceFragment:
        lazy_type = type(value)
        class_ref = imported_name(lazy_type.__module__, lazy_type.__qualname__, context)
        imports = set(class_ref.imports)
        field_ctx = context.indented()
        lines = []
        for field in fields(value):
            if not field.init:
                continue
            current = DataclassFieldAccess.raw_value(value, field.name)
            if context.clean_mode and not self.clean_field_needs_source(value, field, current):
                continue
            fragment = to_source(current, field_ctx)
            imports |= fragment.imports
            lines.append(f"{field.name}={fragment.code}")

        if not lines:
            return SourceFragment(f"{class_ref.code}()", frozenset(imports))
        inner = f",\n{field_ctx.indent_str}".join(lines)
        code = f"{class_ref.code}(\n{field_ctx.indent_str}{inner}\n{context.indent_str})"
        return SourceFragment(code, frozenset(imports))


class LazyDataclassFormatter(LazyResolutionFormatter):
    priority = 37
    formats = LazyDataclass

    def clean_field_needs_source(self, value: object, field: Field, current: object) -> bool:
        if FieldValue.is_inherited(current):
            return False
        if field.name in _set_field_names(value):
            return True
        if isinstance(current, LazyDataclass):
            return not raw_values_equal(current, _field_default(field))
        return True


class FieldValueFormatter(SourceFormatter):
    """Field states render their declared constructor, never a None stand-in."""
    priority = 38
    formats = FieldValue

    def can_format(self, value: object) -> bool:
        return isinstance(value, self.formats)

    def format(self, value: FieldValue, context: FormatContext) -> SourceFragment:
        return value.source(context)
