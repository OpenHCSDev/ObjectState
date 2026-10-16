"""Historical construction declarations, without application lifecycle resources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from inspect import isclass, isroutine

from objectstate.field_value import FieldValue, ConfigValue, Unset
from objectstate.declarations import ValueDeclaration

if TYPE_CHECKING:
    from objectstate.object_state import ObjectState


class DeclarationTarget:
    """A real root namespace, not a synthetic field or a data-kind guess."""

    def __init__(self, value, declaration):
        self.value = value
        self.declaration = declaration

    @property
    def stored(self):
        return self.value

    @property
    def parameter_owner(self):
        return self.declaration.declaring_type

    def read_path(self, path):
        current = self
        for name in path.split('.') if path else ():
            current = current.read_raw(name)
        return current

    def extract_parameters(self, state_type, parameters, structure, prefix='', exclusions=()):
        for name, info in self.declaration.parameters.items():
            if name in exclusions:
                continue
            path = f'{prefix}.{name}' if prefix else name
            structure.declare(path, info, self.parameter_owner)
            member = self.read_raw(name)
            parameters[path] = member
            self.declaration.field_types[name].extract(member, state_type, parameters, structure, path)

    def reconstruct(self, prefix, values, structure, target, *, resolved=False):
        return self.with_fields(structure.direct_values(prefix, values, target, resolved=resolved), resolved=resolved)

    def overlay_fields(self, values):
        return self.with_fields(values)

    def context_configs(self):
        configs = {}
        for name, declaration in self.declaration.context_field_types.items():
            declaration.contribute(self.read_raw(name), configs, source=f'{self.parameter_owner.__name__}.{name}')
        return configs

    def seed_callable_identity(self, memo, seen):
        for name in self.declaration.parameters:
            self.read_raw(name).seed_callable_identity(memo, seen)


class InstanceTarget(DeclarationTarget):
    def context_configs(self):
        configs = super().context_configs()
        for owner in self.declaration.configuration_owners():
            owner.admit_data(self.value).contribute_config(configs, source='context object')
        return configs

    def read_raw(self, name):
        return self.declaration.read_raw(self.value, name)

    def with_fields(self, values, *, resolved=False):
        return type(self)(self.declaration.construct_from(self.value, values, resolved=resolved), self.declaration)


class ClassTarget(DeclarationTarget):
    def read_raw(self, name):
        info = self.declaration.parameters[name]
        return Unset() if info.is_required else self.declaration.field_types[name].admit(info.default_value)

    def with_fields(self, values, *, resolved=False):
        return InstanceTarget(self.declaration.construct({name: member.stored for name, member in values.items()}, resolved=resolved), self.declaration)


class FunctionTarget(ClassTarget):
    def read_raw(self, name):
        info = self.declaration.parameters[name]
        attributes = vars(self.value)
        if name in attributes:
            return self.declaration.field_types[name].admit(attributes[name])
        return Unset() if info.is_required else self.declaration.field_types[name].admit(info.default_value)

    def with_fields(self, values, *, resolved=False):
        return ConfiguredFunctionTarget(self.value, self.declaration, values)


class ConfiguredFunctionTarget(FunctionTarget):
    def __init__(self, value, declaration, values):
        super().__init__(value, declaration)
        self.values = values

    def read_raw(self, name):
        return self.values[name]


def admit_target(value):
    """Decode a root declaration once; nested data uses its field annotation."""
    if isinstance(value, (DeclarationTarget, ConfigValue)):
        return value
    if isclass(value):
        return ClassTarget(value, ValueDeclaration.of(value).owner_scope)
    if isroutine(value):
        return FunctionTarget(value, ValueDeclaration.of(value).owner_scope)
    return InstanceTarget(value, ValueDeclaration.of(type(value)).owner_scope)


class StateScopeOwner(ABC):
    """A declaration that authoritatively owns independently scoped states."""

    __slots__ = ()

    @property
    @abstractmethod
    def owned_scope_ids(self) -> tuple[str, ...]:
        """Project membership from the declaration's existing canonical fields."""

    def validate_scope_membership(
        self, scope: str | None, available: Collection[str]
    ) -> None:
        owned = self.owned_scope_ids
        if len(set(owned)) != len(owned):
            raise ValueError(
                f"ObjectState owner {scope!r} declares duplicate scope membership."
            )
        for child in owned:
            if child not in available:
                raise ValueError(
                    f"ObjectState owner {scope!r} declares missing ObjectState scope {child!r}."
                )


@dataclass(frozen=True)
class StateConstructionBinding(ABC):
    """The actual extraction owner and independently scoped parent of a state."""

    state_type: type[ObjectState]
    target: Any
    parent_scope: str | None
    exclusions: tuple[str, ...]
    parent_field: str | None

    @abstractmethod
    def validate_lifecycle(self, state: ObjectState | None, scope: str) -> None:
        """Validate application ownership before any registry mutation."""

    @abstractmethod
    def attach(self, state: ObjectState) -> None:
        """Install the extraction owner, retaining application lifecycle resources."""

    def prepare(
        self, scope: str, state: ObjectState | None, parent: ObjectState | None
    ) -> ObjectState:
        """Extract a complete replacement schema outside the active registry."""

        self.validate_lifecycle(state, scope)
        prepared = self.state_type(
            object_instance=self.target,
            scope_id=scope,
            parent_state=parent,
            exclude_params=list(self.exclusions),
        )
        prepared._parent_field_name = self.parent_field
        return prepared

    def validate_scope_membership(
        self, prepared: ObjectState, available: Collection[str]
    ) -> None:
        """Validate the prepared raw declaration, not its saved backing target."""

        if isinstance(self.target, StateScopeOwner):
            owner = prepared.to_object(sync_delegate=False)
            if not isinstance(owner, StateScopeOwner):
                raise ValueError(
                    f"Historical scope owner changed role at {prepared.scope_id!r}."
                )
            owner.validate_scope_membership(prepared.scope_id, available)


@dataclass(frozen=True)
class DirectStateBinding(StateConstructionBinding):
    """A declaration whose ObjectState can be constructed independently."""

    def validate_lifecycle(self, state: ObjectState | None, scope: str) -> None:
        if state is not None and (
            type(state) is not self.state_type or state.has_delegate
        ):
            raise ValueError(f"Incompatible direct ObjectState lifecycle at {scope!r}.")

    def attach(self, state: ObjectState) -> None:
        state.object_instance = self.target
        state._target = admit_target(self.target)
        state._delegate_attr = None


@dataclass(frozen=True)
class DelegatedStateBinding(StateConstructionBinding):
    """An editable declaration owned by an already-live application wrapper."""

    lifecycle_type: type
    delegate_attribute: str

    def validate_lifecycle(self, state: ObjectState | None, scope: str) -> None:
        if (
            state is None
            or type(state) is not self.state_type
            or type(state.object_instance) is not self.lifecycle_type
            or state._delegate_attr != self.delegate_attribute
        ):
            raise ValueError(
                f"Missing or incompatible delegated lifecycle at {scope!r}."
            )

    def attach(self, state: ObjectState) -> None:
        setattr(state.object_instance, self.delegate_attribute, self.target)
        state._target = admit_target(self.target)
        state._delegate_attr = self.delegate_attribute
