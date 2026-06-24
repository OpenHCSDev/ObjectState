"""Generic edit-session boundary for ObjectState-backed objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Generic, TypeVar, cast

if TYPE_CHECKING:
    from objectstate.object_state import ObjectState


EditedObjectT = TypeVar("EditedObjectT")


@dataclass(slots=True)
class ObjectStateEditSession(Generic[EditedObjectT]):
    """Reconstruct and inspect an edited object through ObjectState.

    ObjectState owns parameter storage, dirty state, lazy dataclass
    reconstruction, and save/cancel baselines. This session is a small
    fail-loud boundary for windows or other callers that need the current
    edited object without reimplementing ObjectState semantics.
    """

    state_provider: Callable[[], ObjectState | None]
    fallback_object: EditedObjectT | None = None
    expected_type: type[EditedObjectT] | None = None

    @property
    def state(self) -> ObjectState | None:
        return self.state_provider()

    def require_state(self, parameter_name: str) -> ObjectState:
        state = self.state
        if state is None:
            raise KeyError(
                f"ObjectStateEditSession has no state for parameter {parameter_name!r}"
            )
        return state

    def to_object(self, *, update_delegate: bool = False) -> EditedObjectT:
        state = self.state
        if state is None:
            value = self.fallback_object
        else:
            value = state.to_object(update_delegate=update_delegate)

        if value is None:
            raise RuntimeError("ObjectStateEditSession has no object to reconstruct")
        if self.expected_type is not None and not isinstance(value, self.expected_type):
            raise TypeError(
                "ObjectStateEditSession reconstructed "
                f"{type(value).__name__}; expected {self.expected_type.__name__}"
            )
        return cast(EditedObjectT, value)

    def has_parameter(self, parameter_name: str) -> bool:
        state = self.state
        return state is not None and parameter_name in state.parameters

    def parameter_value(self, parameter_name: str):
        state = self.require_state(parameter_name)
        if parameter_name not in state.parameters:
            raise KeyError(f"ObjectState parameter does not exist: {parameter_name!r}")
        return state.parameters[parameter_name]

    def update_parameter(self, parameter_name: str, value) -> None:
        state = self.require_state(parameter_name)
        if parameter_name not in state.parameters:
            raise KeyError(f"ObjectState parameter does not exist: {parameter_name!r}")
        state.update_parameter(parameter_name, value)
