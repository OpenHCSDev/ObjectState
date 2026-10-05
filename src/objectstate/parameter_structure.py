"""Canonical extraction structure, separate from live/saved parameter values."""

from __future__ import annotations

import copy
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
