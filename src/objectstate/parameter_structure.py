"""Canonical extraction structure, separate from live/saved parameter values."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any

from python_introspect import ParameterInfo

from objectstate.field_access import DottedFieldPath
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

    @property
    def defaults(self) -> dict[str, Any]:
        """Derive editor reset values from admitted parameter declarations."""

        return {path: info.default_value for path, info in self.declarations.items()}

    @property
    def descriptions(self) -> dict[str, str | None]:
        """Request presentation help only when a consumer reads it."""

        return {path: info.description for path, info in self.declarations.items()}

    def index(self, parameters: dict[str, Any]) -> None:
        """Derive direct-child topology from this epoch's admitted values."""

        paths_by_owner: dict[DottedFieldPath, list[DottedFieldPath]] = {}
        for name in parameters:
            path = DottedFieldPath(name)
            paths_by_owner.setdefault(path.parent, []).append(path)
        self.direct_paths = {
            owner: tuple(paths) for owner, paths in paths_by_owner.items()
        }

    def without_descendants(self, prefix: str) -> ParameterStructure:
        """Prepare a subtree replacement without publishing live metadata."""

        prepared = self.clone()
        descendant = f"{prefix}."
        prepared.declarations = {
            path: info for path, info in self.declarations.items()
            if not path.startswith(descendant)
        }
        prepared.owner_paths = {
            path: owner for path, owner in self.owner_paths.items()
            if not path.startswith(descendant)
        }
        return prepared

    def path(self, name: str) -> DottedFieldPath:
        """Resolve a name to its admitted path, without analyzing declarations."""

        requested = DottedFieldPath(name)
        for path in self.direct_paths.get(requested.parent, ()):
            if path.value == name:
                return path
        raise KeyError(f"ObjectState path is not registered: {name!r}")

    def ancestors(self, path: DottedFieldPath) -> tuple[DottedFieldPath, ...]:
        """The admitted fields down to this one, itself last."""

        return tuple(self.path(step.value) for step in reversed(path.lineage))

    def leaf_paths(self, parent: str = "") -> Iterator[DottedFieldPath]:
        """Enumerate leaves through the extracted topology, never the source type."""

        for path in self.direct_paths.get(DottedFieldPath(parent), ()):
            if self.direct_paths.get(path):
                yield from self.leaf_paths(path.value)
            else:
                yield path

    def inheritance_field_paths(
        self, target_type: ParameterOwner, field_name: str
    ) -> tuple[str, ...]:
        """Find inheriting fields in this structure's epoch, not another one."""
        from objectstate.lazy_factory import get_base_type_for_lazy

        target_base = (
            get_base_type_for_lazy(target_type) or target_type
            if isinstance(target_type, type) else target_type
        )
        paths: list[str] = []
        for path, owner in self.owner_paths.items():
            if DottedFieldPath(path).field_name != field_name:
                continue
            owner_base = (
                get_base_type_for_lazy(owner) or owner
                if isinstance(owner, type) else owner
            )
            matches = owner_base == target_base
            if not matches and isinstance(owner_base, type) and isinstance(target_base, type):
                matches = any(
                    (get_base_type_for_lazy(base) or base) == target_base
                    for base in owner_base.__mro__
                )
            if matches:
                paths.append(path)
        return tuple(paths)

    def is_container_parameter(
        self, name: str, value: Any, parameters: dict[str, Any]
    ) -> bool:
        """Identify a nested dataclass entry from its actual extracted children."""

        if value is None or not is_dataclass(type(value)):
            return False
        prefix = f"{name}."
        return any(path.startswith(prefix) for path in parameters)

    @classmethod
    def for_target(
        cls, target: Any, exclusions: list[str] | None
    ) -> ParameterStructure:
        """Start extraction from the actual target's excluded constructor values."""

        names = list(exclusions or [])
        return cls(
            exclusions=names,
            excluded_values={
                name: getattr(target, name) for name in names if hasattr(target, name)
            },
        )

    def clone(self) -> ParameterStructure:
        """Detach owned maps without cloning declaration/target identities.

        Used only for prepared schema transfer and local rollback. Historical
        values are detached as a complete deep-copied construction/value graph.
        """

        return replace(
            self,
            **{item.name: copy.copy(getattr(self, item.name)) for item in fields(self)},
        )
