"""Historical construction declarations, without application lifecycle resources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from objectstate.object_state import ObjectState


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
        state._extraction_target = self.target
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
        state._extraction_target = self.target
        state._delegate_attr = self.delegate_attribute
