"""Behavior compiled from declarations; field data never chooses its kind."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import copy
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from enum import Enum
from functools import cache, cached_property
from inspect import isclass
from typing import Any, ClassVar, get_args, get_origin, get_type_hints

from python_introspect import UnifiedParameterAnalyzer, resolve_annotated, resolve_declared_type
from python_introspect.annotation_types import is_union_type

from objectstate import field_value as members
from objectstate.field_access import DataclassFieldAccess


@dataclass(frozen=True, slots=True)
class InheritedDefault(ABC):
    @abstractmethod
    def value(self):
        """Materialize the one declared inherited default."""


@dataclass(frozen=True, slots=True)
class ValueDefault(InheritedDefault):
    schema_origin: ClassVar[str] = 'inherited_default'
    default: object

    def value(self):
        return self.default


@dataclass(frozen=True, slots=True)
class FactoryDefault(InheritedDefault):
    schema_origin: ClassVar[str] = 'inherited_factory'
    factory: object

    def value(self):
        return self.factory()


class ConfigurationRebuild(ABC):
    """A configuration declaring construction different from keyword init."""
    __slots__ = ()
    @classmethod
    @abstractmethod
    def from_fields(cls, **values):
        """Construct from declared init fields."""


class ValueDeclaration(ABC):
    def __init__(self, annotation):
        self.annotation = annotation

    @staticmethod
    def of(annotation):
        return _compile_declaration(resolve_annotated(annotation))

    def admit(self, value):
        return members.FieldValue.of(value).map(self.admit_data)

    def scope_available(self, member):
        return member.available()

    @abstractmethod
    def admit_data(self, value):
        """Box using behavior selected by this annotation."""

    @abstractmethod
    def configuration_owners(self):
        """The configuration declarations this type admits."""

    @abstractmethod
    def choose_declaration(self, consumer, **arguments):
        """Consume the annotation's form capability."""

    def convert_structure(self, consumer, value, name):
        return consumer.convert_leaf_structure(value, self.annotation, name)

    def editing_default(self, factory):
        return members.Inherit()

    def lazy_field(self, declaration, annotation, factory):
        metadata = dict(declaration.metadata)
        if declaration.default is not MISSING:
            metadata[InheritedDefault] = ValueDefault(declaration.default)
        elif declaration.default_factory is not MISSING:
            metadata[InheritedDefault] = FactoryDefault(declaration.default_factory)
        return annotation, field(default=members.Inherit(), metadata=metadata)

    def require_config_type(self):
        raise TypeError(f'Expected a configuration declaration, got {self.annotation!r}')

    @cached_property
    def owner_scope(self):
        return ConstructorDeclaration(self.annotation)

    def declared_config_slot(self, name):
        return tuple((name, owner.declaring_type) for owner in self.configuration_owners())


class ScalarDeclaration(ValueDeclaration):
    def __init__(self, annotation, member_type=members.Value):
        super().__init__(annotation)
        self.member_type = member_type

    def admit_data(self, value):
        return self.member_type(value)

    def configuration_owners(self):
        return ()

    def choose_declaration(self, consumer, **arguments):
        return consumer.scalar_declaration(self.annotation, **arguments)

    def extract(self, member, state_type, parameters, structure, path):
        return None

    def descendants(self, member, path, registered):
        return {}

    def contribute(self, member, configs, *, source):
        return None


class CollectionDeclaration(ScalarDeclaration):
    def admit_data(self, value):
        return members.CollectionValue(value, self)

    def serialize(self, member, resolver):
        return member.fold(lambda value: self.rebuild((key, item.for_serialization(resolver))
                           for key, item in self.items(value)), lambda directive: directive)


class SequenceDeclaration(CollectionDeclaration):
    def __init__(self, annotation, container):
        super().__init__(annotation)
        self.container = container

    @abstractmethod
    def item_declaration(self, index):
        """Admit this index through its declared element annotation."""

    def items(self, value):
        return ((index, self.item_declaration(index).admit(child))
                for index, child in enumerate(value))

    def child_path(self, path, key):
        return path.child_index(key)

    def rebuild(self, items):
        return self.container(member for key, member in items)


class RepeatedSequenceDeclaration(SequenceDeclaration):
    def __init__(self, annotation, container, item):
        super().__init__(annotation, container)
        self.item = item

    def item_declaration(self, index):
        return self.item


class FixedTupleDeclaration(SequenceDeclaration):
    def __init__(self, annotation, items):
        super().__init__(annotation, tuple)
        self.item_types = items

    def item_declaration(self, index):
        return self.item_types[index]


class MappingDeclaration(CollectionDeclaration):
    def __init__(self, annotation, key, item):
        super().__init__(annotation)
        self.key = key
        self.item = item

    def items(self, value):
        return ((key, self.item.admit(child)) for key, child in value.items())

    def child_path(self, path, key):
        return path.child_field(str(key))

    def rebuild(self, items):
        return dict(items)

    def serialize(self, member, resolver):
        return member.fold(lambda value: {
            self.key.admit(key).for_serialization(resolver): item.for_serialization(resolver)
            for key, item in self.items(value)
        }, lambda directive: directive)


class NullableDeclaration(ValueDeclaration):
    def __init__(self, annotation, inner):
        super().__init__(annotation)
        self.inner = inner

    def admit_data(self, value):
        return members.NullValue() if value is None else self.inner.admit_data(value)

    def scope_available(self, member):
        return member.fold(lambda value: value is not None, lambda directive: False)

    def configuration_owners(self):
        return self.inner.configuration_owners()

    def choose_declaration(self, consumer, **arguments):
        return self.inner.choose_declaration(consumer, **arguments)

    def convert_structure(self, consumer, value, name):
        return None if value is None else self.inner.convert_structure(consumer, value, name)

    def extract(self, member, state_type, parameters, structure, path):
        return member.fold(lambda value: None if value is None else self.inner.extract(self.inner.admit_data(value), state_type, parameters, structure, path), lambda directive: None)

    def descendants(self, member, path, registered):
        return member.fold(lambda value: {} if value is None else self.inner.descendants(self.inner.admit_data(value), path, registered), lambda directive: {})

    def contribute(self, member, configs, *, source):
        return member.fold(lambda value: None if value is None else self.inner.contribute(self.inner.admit_data(value), configs, source=source), lambda directive: None)

    def resolved_child(self, member, name, owner):
        return member.fold(lambda value: (members.Unset(), owner) if value is None else self.inner.resolved_child(self.inner.admit_data(value), name, owner), lambda directive: (members.Unset(), owner))


class ParameterOwnerDeclaration(ValueDeclaration):
    @property
    def declaring_type(self):
        return self.annotation

    @cached_property
    def base_type(self):
        return resolve_declared_type(self.declaring_type)

    @cached_property
    def parameters(self):
        return UnifiedParameterAnalyzer.analyze(self.declaring_type)

    @cached_property
    def field_types(self):
        return {name: ValueDeclaration.of(info.param_type) for name, info in self.parameters.items()}

    @property
    def annotations(self):
        return {name: info.param_type for name, info in self.parameters.items()}

    @cached_property
    def context_field_types(self):
        annotations = get_type_hints(self.declaring_type, include_extras=True) if isclass(self.declaring_type) else {}
        return {**self.field_types, **{name: ValueDeclaration.of(annotation) for name, annotation in annotations.items()}}

    @property
    def init_field_names(self):
        return tuple(self.parameters)

    @property
    def owner_scope(self):
        return self

    def construct(self, values, *, resolved=False):
        constructor = self.base_type if resolved else self.declaring_type
        return constructor(**{name: value for name, value in values.items() if name in self.init_field_names})


class ConstructorDeclaration(ParameterOwnerDeclaration):
    def admit_data(self, value):
        return members.Value(value)

    def configuration_owners(self):
        return ()

    def choose_declaration(self, consumer, **arguments):
        return consumer.scalar_declaration(self.annotation, **arguments)

    def read_raw(self, value, name):
        return self.context_field_types[name].admit(getattr(value, name))

    def construct_from(self, value, values, *, resolved=False):
        result = copy(value)
        for name in self.init_field_names:
            if name in values:
                setattr(result, name, values[name].stored)
        return result


class ConfigurationDeclaration(ParameterOwnerDeclaration):
    @cached_property
    def fields(self):
        return tuple(item for item in fields(self.declaring_type) if item.init)

    def admit_data(self, value):
        return members.ConfigValue(value, self)

    def require_config_type(self):
        return self.declaring_type

    def declared_fields(self):
        return self.fields

    def field_annotations(self):
        return self.annotations

    def configuration_fields(self):
        return tuple((name, owner.declaring_type) for name, declaration in self.field_types.items() for owner in declaration.configuration_owners())

    def configuration_owners(self):
        return (self,)

    def configuration_mro(self, field_name):
        for owner in self.declaring_type.__mro__:
            for declaration in ValueDeclaration.of(owner).configuration_owners():
                if field_name in declaration.context_field_types:
                    yield declaration

    def choose_declaration(self, consumer, **arguments):
        return consumer.config_declaration(self.declaring_type, **arguments)

    def convert_structure(self, consumer, value, name):
        if isinstance(value, self.declaring_type):
            return value
        if not isinstance(value, dict):
            return super().convert_structure(consumer, value, name)
        unknown = value.keys() - set(self.init_field_names)
        if unknown:
            raise ValueError(f'Unknown fields for {self.declaring_type.__name__}: {tuple(unknown)!r}')
        return self.construct({key: consumer.convert_value_to_type(datum, self.annotations[key], key) for key, datum in value.items()})

    def own_default(self, name):
        declaration = self.declaring_type.__dataclass_fields__[name]
        if InheritedDefault in declaration.metadata:
            return members.Unset()
        if declaration.default is not MISSING:
            return self.context_field_types[name].admit(declaration.default)
        if declaration.default_factory is not MISSING:
            return self.context_field_types[name].admit(declaration.default_factory())
        return members.Unset()

    def inherited_default(self, name):
        declaration = self.declaring_type.__dataclass_fields__[name]
        if InheritedDefault in declaration.metadata:
            return self.context_field_types[name].admit(declaration.metadata[InheritedDefault].value())
        return members.Unset()

    def frozen_declaration(self):
        return self.declaring_type.__dataclass_params__.frozen

    def lazy_field(self, declaration, annotation, factory):
        return factory.configuration_field(self, declaration, annotation)

    def editing_default(self, factory):
        return factory.configuration_editing_default(self)

    def serialize(self, member, resolver):
        def data(value):
            arguments = {}
            for name in self.init_field_names:
                raw = self.read_raw(value, name)
                resolved = raw.resolve(lambda name=name: self.field_types[name].admit(resolver(self.declaring_type, name).value))
                arguments[name] = resolved.for_serialization(resolver)
            return self.construct(arguments, resolved=True)
        return member.fold(data, lambda directive: directive)

    def read_raw(self, value, name):
        return self.context_field_types[name].admit(DataclassFieldAccess.raw_value(value, name))

    def extract(self, member, state_type, parameters, structure, path):
        return member.fold(lambda value: self.admit_data(value).extract_parameters(state_type, parameters, structure, path), lambda directive: None)

    def descendants(self, member, path, registered):
        return member.fold(lambda value: self.admit_data(value).descendant_values(path, registered), lambda directive: {})

    def contribute(self, member, configs, *, source):
        return member.fold(lambda value: self.admit_data(value).contribute_config(configs, source=source), lambda directive: None)

    def resolved_child(self, member, name, owner):
        return member.fold(lambda value: (self.read_raw(value, name), self.declaring_type), lambda directive: (members.Unset(), owner))

    def accepts(self, expected_type):
        return issubclass(self.base_type, resolve_declared_type(expected_type))

    def construct_from(self, value, updates, *, resolved=False):
        arguments = {name: DataclassFieldAccess.raw_value(value, name) for name in self.init_field_names}
        arguments.update({name: member.stored for name, member in updates.items() if name in self.init_field_names})
        return self.construct(arguments, resolved=resolved)

    def rebuild(self, value, updates, *, resolved=False):
        result = self.construct_from(value, updates, resolved=resolved)
        declaration = ValueDeclaration.of(self.base_type) if resolved else self
        return declaration.admit_data(result)


class RebuildableConfigurationDeclaration(ConfigurationDeclaration):
    def construct(self, values, *, resolved=False):
        constructor = self.base_type if resolved else self.declaring_type
        return constructor.from_fields(**{name: value for name, value in values.items() if name in self.init_field_names})


def admit_root_value(value):
    """Capture a root model's owner; nested fields never infer owners from data."""
    if isinstance(value, members.FieldValue):
        return value
    return ValueDeclaration.of(type(value)).admit(value)


@cache
def _compile_declaration(annotation):
    """One shape decision, whose input is an annotation rather than field data."""
    if is_union_type(annotation):
        arms = get_args(annotation)
        nonnull = tuple(arm for arm in arms if arm is not type(None))
        if len(nonnull) == 1 and len(nonnull) != len(arms):
            return NullableDeclaration(annotation, ValueDeclaration.of(nonnull[0]))
    origin = get_origin(annotation) or annotation
    arguments = get_args(annotation)
    if origin in (list, tuple):
        if origin is tuple and arguments and arguments[-1] is not Ellipsis:
            return FixedTupleDeclaration(annotation, tuple(ValueDeclaration.of(item) for item in arguments))
        return RepeatedSequenceDeclaration(annotation, origin, ValueDeclaration.of(arguments[0] if arguments else Any))
    if origin is dict:
        key, item = arguments if arguments else (Any, Any)
        return MappingDeclaration(annotation, ValueDeclaration.of(key), ValueDeclaration.of(item))
    if annotation is type(None):
        return ScalarDeclaration(annotation, members.NullValue)
    if isinstance(annotation, type):
        if is_dataclass(annotation):
            declaration = RebuildableConfigurationDeclaration if issubclass(annotation, ConfigurationRebuild) else ConfigurationDeclaration
            return declaration(annotation)
        if issubclass(annotation, Enum):
            return ScalarDeclaration(annotation, members.EnumValue)
        if issubclass(annotation, str):
            return ScalarDeclaration(annotation, members.TextValue)
    return ScalarDeclaration(annotation)
