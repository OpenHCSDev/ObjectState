"""Canonical extraction structure, separate from live/saved parameter values."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import Any

from python_introspect import ParameterInfo

from objectstate.field_access import DottedFieldPath
from objectstate.field_value import Unset
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

    def declare(self, path: str, info: ParameterInfo) -> ParameterInfo:
        """Admit external signature absence once, as Unset rather than None."""
        declaration = info._replace(default_value=Unset()) if info.is_required else info
        self.declarations[path] = declaration
        return declaration

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

    def reconstruct(self, prefix, values, target, *, resolved=False):
        """Build one projection from its own payload, preserving scalar terminals.

        A container's stored None/Inherit/Unset is authoritative even when an
        editor retains child drafts. Nominal type comes from that payload, never
        from the declaration-owner index. Live and saved projections share this.
        """
        from objectstate.field_access import DataclassFieldAccess
        from objectstate.lazy_factory import get_base_type_for_lazy, replace_raw

        prototype = values[prefix] if prefix else target
        if prefix and not is_dataclass(prototype):
            return prototype
        prefix_dot = f"{prefix}." if prefix else ""
        direct = {}
        for path, value in values.items():
            if not path.startswith(prefix_dot):
                continue
            remainder = path[len(prefix_dot):]
            if "." in remainder:
                continue
            direct[remainder] = (
                self.reconstruct(path, values, target, resolved=resolved)
                if is_dataclass(value) else value
            )
        if not prefix:
            direct.update(self.excluded_values)
        if is_dataclass(prototype):
            if not resolved:
                return replace_raw(prototype, **direct)
            constructor = get_base_type_for_lazy(type(prototype)) or type(prototype)
            arguments = DataclassFieldAccess.raw_init_values(prototype, constructor)
            arguments.update(direct)
            return constructor(**arguments)
        return type(prototype)(**direct)
