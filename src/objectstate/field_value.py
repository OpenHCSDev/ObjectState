"""Stored meaning and declaration-admitted configuration capabilities."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from pycodify import SourceFragment, imported_name, to_source

from objectstate.field_access import DottedFieldPath
from objectstate.value_semantics import semantic_values_equal, seed_callable_identity


@dataclass(eq=False, repr=False)
class FieldValue(ABC):
    __slots__ = ()

    @classmethod
    def of(cls, value: Any) -> FieldValue:
        return value if isinstance(value, cls) else Value(value)

    @abstractmethod
    def available(self):
        """Whether domain data is supplied, including literal null."""

    def inherits(self):
        return False

    def inherited_from(self, resolved):
        return False

    @abstractmethod
    def present_to(self, display):
        """Paint data or a directive through its declared operation."""

    @abstractmethod
    def map(self, convert):
        """Convert data, preserving directives."""

    @abstractmethod
    def fold(self, data, directive):
        """Consume both meanings explicitly without probing their payloads."""

    def project(self, convert):
        return convert(self.stored)

    @abstractmethod
    def resolve(self, inherited):
        """Only inheritance requests context lookup."""

    @abstractmethod
    def overlay(self, base):
        """Apply this meaning over another admitted member."""

    @property
    def stored(self):
        return self

    def __repr__(self):
        return f'{type(self).__name__}()'

    def __eq__(self, other):
        return type(self) is type(other)

    def __hash__(self):
        return hash(type(self))

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def source(self, context):
        reference = imported_name(type(self).__module__, type(self).__qualname__, context)
        return SourceFragment(f'{reference.code}()', reference.imports)


class LeafValue(FieldValue):
    """Terminal meanings do not implement field or child access."""
    __slots__ = ()

    def notification_paths(self, path, structure):
        return {path}

    def payload_types(self, path):
        return ()

    def source_equals(self, other):
        return self == other

    def reconstruct(self, prefix, values, structure, target, *, resolved=False):
        return self

    def merge_config(self, override):
        return override

    def history_changes(self, before, path):
        return before.history_to_leaf(self, path)

    def history_to_leaf(self, after, path):
        return {} if self == after else {path: (self, after)}

    def history_to_config(self, after, path):
        return {path: (self, after)}

    def structural_leaves(self, path):
        return ((path, self.stored),)

    def placeholder_text(self, *, nested=False):
        return str(self)

    def for_serialization(self, resolver):
        return self.stored


class DirectiveValue(LeafValue):
    __slots__ = ()

    def available(self):
        return False

    def present_to(self, display):
        display.present_directive(self)

    def map(self, convert):
        return self

    def fold(self, data, directive):
        return directive(self)

    def seed_callable_identity(self, memo, seen):
        memo[id(self)] = self

    def contribute_config(self, configs, *, source, expected_type=None):
        return None


@dataclass(eq=False, repr=False)
class Inherit(DirectiveValue):
    __slots__ = ()

    def inherits(self):
        return True

    def inherited_from(self, resolved):
        return resolved.available()

    def resolve(self, inherited):
        return inherited()

    def overlay(self, base):
        return base


@dataclass(eq=False, repr=False)
class Unset(DirectiveValue):
    __slots__ = ()

    def resolve(self, inherited):
        return self

    def overlay(self, base):
        return self


@dataclass(eq=False, repr=False)
class Value(LeafValue):
    __slots__ = ('value',)
    value: Any

    def __init__(self, value):
        self.value = value

    def available(self):
        return True

    def present_to(self, display):
        display.present_value(self.value)

    def resolve(self, inherited):
        return self

    def map(self, convert):
        return convert(self.value)

    def fold(self, data, directive):
        return data(self.value)

    def overlay(self, base):
        return self

    @property
    def stored(self):
        return self.value

    def seed_callable_identity(self, memo, seen):
        seed_callable_identity(self.value, memo, seen)

    def placeholder_text(self, *, nested=False):
        return str(self.value)

    def for_serialization(self, resolver):
        return self.value

    def render_preview(self, consumer, request):
        return consumer.scalar_preview(request)

    def __eq__(self, other):
        return isinstance(other, Value) and semantic_values_equal(self.value, other.value)

    __hash__ = None

    def __deepcopy__(self, memo):
        return type(self)(deepcopy(self.value, memo))

    def source(self, context):
        return to_source(self.value, context)


class NullValue(Value):
    __slots__ = ()

    def __init__(self, value=None):
        super().__init__(value)

    def placeholder_text(self, *, nested=False):
        return '(none)'

    def contribute_config(self, configs, *, source, expected_type=None):
        return None


class EnumValue(Value):
    __slots__ = ()

    def placeholder_text(self, *, nested=False):
        return f'{self.value.__class__.__name__}.{self.value.name}'


class TextValue(Value):
    __slots__ = ()

    def placeholder_text(self, *, nested=False):
        return self.value[:17] + '...' if nested and len(self.value) > 20 else self.value


class ConfigurationFields:
    """Actual configuration field capability; terminal values never inherit it."""
    __slots__ = ()

    def declared_fields(self):
        return self.declaration.fields

    def field_annotations(self):
        return self.declaration.annotations

    def read_raw(self, name):
        return self.declaration.read_raw(self.value, name)

    def stored_child(self, name):
        return self.read_raw(name)

    def resolved_child(self, name, owner):
        return self.read_raw(name), self.declaration.declaring_type

    def read_path(self, path):
        current = self
        for part in DottedFieldPath(path).parts:
            current = current.read_raw(part)
        return current

    def descendant_values(self, prefix, registered):
        updates = {}
        for declaration in self.declared_fields():
            path = f'{prefix}.{declaration.name}'
            member = self.read_raw(declaration.name)
            if path in registered:
                updates[path] = member
            updates.update(self.declaration.field_types[declaration.name].descendants(member, path, registered))
        return updates


class DeclaredValue(Value):
    __slots__ = ('declaration',)

    def __init__(self, value, declaration):
        super().__init__(value)
        self.declaration = declaration

    def __deepcopy__(self, memo):
        return type(self)(deepcopy(self.value, memo), self.declaration)

    def for_serialization(self, resolver):
        return self.declaration.serialize(self, resolver)


class CollectionValue(DeclaredValue):
    def structural_leaves(self, path):
        for key, member in self.declaration.items(self.value):
            yield from member.structural_leaves(self.declaration.child_path(path, key))

    def seed_callable_identity(self, memo, seen):
        for key, member in self.declaration.items(self.value):
            seed_callable_identity(key, memo, seen)
            member.seed_callable_identity(memo, seen)

    def __eq__(self, other):
        return (isinstance(other, CollectionValue)
                and self.declaration.annotation == other.declaration.annotation
                and semantic_values_equal(dict(self.declaration.items(self.value)),
                                          dict(other.declaration.items(other.value))))

    __hash__ = None


class ConfigValue(ConfigurationFields, DeclaredValue):
    @property
    def parameter_owner(self):
        return self.declaration.declaring_type

    def __eq__(self, other):
        return (isinstance(other, ConfigValue)
                and self.declaration.declaring_type is other.declaration.declaring_type
                and all(self.read_raw(item.name) == other.read_raw(item.name) for item in self.declared_fields()))

    __hash__ = None

    def source_equals(self, other):
        return (isinstance(other, ConfigValue)
                and self.declaration.base_type is other.declaration.base_type
                and all(self.read_raw(name).source_equals(other.read_raw(name))
                        for name in self.declaration.init_field_names))

    def render_preview(self, consumer, request):
        return consumer.configuration_preview(request)

    def projection_fields(self):
        return ((item, self.read_raw(item.name)) for item in self.declared_fields())

    def extract_parameters(self, state_type, parameters, structure, prefix='', exclusions=()):
        for name, info in self.declaration.parameters.items():
            if name in exclusions:
                continue
            path = f'{prefix}.{name}' if prefix else name
            structure.declare(path, info, self.parameter_owner)
            member = self.read_raw(name)
            parameters[path] = member
            self.declaration.field_types[name].extract(member, state_type, parameters, structure, path)

    def payload_types(self, path):
        return ((path, self.declaration.base_type),)

    def notification_paths(self, path, structure):
        return set() if structure.direct_paths.get(DottedFieldPath(path)) else {path}

    def with_fields(self, values, *, resolved=False):
        return self.declaration.rebuild(self.value, values, resolved=resolved)

    def reconstruct(self, prefix, values, structure, target, *, resolved=False):
        return self.with_fields(structure.direct_values(prefix, values, target, resolved=resolved), resolved=resolved)

    def overlay_fields(self, values):
        return self.with_fields(values) if values else self

    def overlay(self, base):
        return base.merge_config(self)

    def merge_config(self, override):
        owner = self if self.declaration.base_type is override.declaration.base_type else override
        base_names = self.declaration.field_types.keys()
        values = {item.name: override.read_raw(item.name).overlay(self.read_raw(item.name))
                  for item in override.declared_fields() if item.name in base_names}
        return owner.with_fields(values) if values else owner

    def history_changes(self, before, path):
        return before.history_to_config(self, path)

    def history_to_config(self, after, path):
        return {} if self.declaration.base_type is after.declaration.base_type else {path: (self, after)}

    def structural_leaves(self, path):
        for item in self.declared_fields():
            yield from self.read_raw(item.name).structural_leaves(path.child_field(item.name))

    def seed_callable_identity(self, memo, seen):
        for item in self.declared_fields():
            self.read_raw(item.name).seed_callable_identity(memo, seen)

    def placeholder_text(self, *, nested=False):
        name = self.declaration.declaring_type.__name__
        if nested:
            return f'{name}(...)'
        summaries = [f'{item.name}={self.read_raw(item.name).placeholder_text(nested=True)}'
                     for item in self.declared_fields()]
        return ', '.join(summaries) if summaries else f'{name} (default settings)'

    def context_configs(self):
        configs = {}
        self.contribute_config(configs, source='context object')
        for name, declaration in self.declaration.field_types.items():
            declaration.contribute(self.read_raw(name), configs, source=f'{self.parameter_owner.__name__}.{name}')
        return configs

    def contribute_config(self, configs, *, source, expected_type=None):
        actual = self.declaration.base_type
        if expected_type is not None and not self.declaration.accepts(expected_type):
            raise TypeError(f'{source} does not declare {expected_type.__name__}.')
        if actual in configs and configs[actual].stored is not self.value:
            raise ValueError(f'{source} introduces a second {actual.__name__} instance into one configuration context.')
        configs[actual] = self
