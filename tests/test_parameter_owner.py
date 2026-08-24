"""Tests for the canonical ObjectState parameter-owner declaration."""

from typing import get_type_hints

from objectstate import ObjectState, ParameterOwner
from objectstate.object_state_registry import DeferredFieldInvalidation


def test_objectstate_surfaces_share_parameter_owner_authority() -> None:
    assert get_type_hints(ObjectState.type_for_path)["return"] == ParameterOwner
    assert get_type_hints(DeferredFieldInvalidation)["changed_type"] == ParameterOwner
