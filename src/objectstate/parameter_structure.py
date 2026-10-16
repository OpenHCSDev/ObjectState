"""Canonical extraction structure, separate from live/saved parameter values."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields, replace
from typing import Any

from python_introspect import ParameterInfo, resolve_declared_type

from objectstate.field_access import DataclassFieldAccess, DottedFieldPath
from objectstate.field_value import FieldValue, Unset
from objectstate.declarations import ValueDeclaration
from objectstate.construction_binding import admit_target
from objectstate.parameter_owner import ParameterOwner


@dataclass
class ParameterStructure:
    """One owner for extracted topology, defaults, descriptions and exclusions."""

    owner_paths: dict[str, ParameterOwner] = field(default_factory=dict)
    direct_paths: dict[DottedFieldPath, tuple[DottedFieldPath, ...]] = field(
        default_factory=dict
    )
    declarations: dict[str, ParameterInfo] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    excluded_values: dict[str, Any] = field(default_factory=dict)

    def declare(self, path: str, info: ParameterInfo, owner: ParameterOwner) -> ParameterInfo:
        """Admit a declaration and its owner together, never the payload's type."""
        declaration = info._replace(default_value=Unset() if info.is_required else ValueDeclaration.of(info.param_type).admit(info.default_value))
        self.declarations[path] = declaration
        self.owner_paths[path] = owner
        return declaration

    def binding_owner(self, path: str) -> ParameterOwner:
        """Immutable declaration identity survives schema copying and undo."""
        return resolve_declared_type(self.owner_paths[path])

    def admit(self, path, value):
        return ValueDeclaration.of(self.declarations[path].param_type).admit(value)

    def descendants(self, path, value, registered):
        return ValueDeclaration.of(self.declarations[path].param_type).descendants(value, path, registered)

    def resolved_child(self, parent, value, name, owner):
        return ValueDeclaration.of(self.declarations[parent].param_type).resolved_child(value, name, owner)

    def container_types(self, values: dict[str, Any]):
        """Nominal payload types come from the projection, not declaration owners."""
        for path, member in values.items():
            yield from member.payload_types(path)

    def affected_paths(self, changed):
        """A container's presence/source is a dependency of every declared child."""
        affected = set(changed) & self.declarations.keys()
        pending = list(affected)
        while pending:
            for child in self.direct_paths.get(DottedFieldPath(pending.pop()), ()):
                if child.value not in affected:
                    affected.add(child.value)
                    pending.append(child.value)
        return affected

    @property
    def defaults(self) -> dict[str, Any]:
        """Derive editor reset values from admitted parameter declarations."""

        return {path: info.default_value for path, info in self.declarations.items()}

    @property
    def descriptions(self) -> dict[str, str | None]:
        """Request presentation help only when a consumer reads it."""

        return {path: info.description for path, info in self.declarations.items()}

    @classmethod
    def for_target(
        cls, target: Any, exclusions: list[str] | None
    ) -> ParameterStructure:
        """Start extraction from the actual target's excluded constructor values."""

        names = list(exclusions or [])
        return cls(
            exclusions=names,
            excluded_values={name: target.read_raw(name) for name in names},

        )

    @classmethod
    def project_target(cls, target, state_type):
        namespace = admit_target(target)
        structure = cls.for_target(namespace, None)
        values = {}
        namespace.extract_parameters(state_type, values, structure)
        return values

    def clone(self) -> ParameterStructure:
        """Detach owned maps without cloning declaration/target identities.

        Used only for prepared schema transfer and local rollback. Historical
        values are detached as a complete deep-copied construction/value graph.
        """

        return replace(
            self,
            **{item.name: copy.copy(getattr(self, item.name)) for item in fields(self)},
        )

    def direct_values(self, prefix, values, target, *, resolved=False):
        """Project topology; each admitted member owns reconstruction behavior."""
        prefix_dot = f'{prefix}.' if prefix else ''
        direct = {
            path[len(prefix_dot):]: self.reconstruct_member(path, values, target, resolved=resolved)
            for path in values
            if path.startswith(prefix_dot) and '.' not in path[len(prefix_dot):]
        }
        if not prefix:
            direct.update(self.excluded_values)
        return direct

    def reconstruct_member(self, prefix, values, target, *, resolved=False):
        prototype = values.get(prefix, Unset()) if prefix else target
        return prototype.reconstruct(prefix, values, self, target, resolved=resolved)

    def reconstruct(self, prefix, values, target, *, resolved=False):
        """Expose domain data only at the reconstruction boundary."""
        return self.reconstruct_member(prefix, values, target, resolved=resolved).stored
