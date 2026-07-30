from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from objectstate import (
    ObjectState,
    ObjectStateRegistry,
    ObjectStateTransactionCheckpoint,
)


def _callback(value: int) -> int:
    return value + 1


@dataclass(frozen=True)
class CallbackConfig:
    value: int = 1
    callback: Callable[[int], int] = _callback


class DelegatedHost:
    __objectstate_delegate__ = "config"

    def __init__(self, config: CallbackConfig) -> None:
        self.config = config


def test_checkpoint_restores_exact_dirty_nondelegated_state() -> None:
    original = CallbackConfig()
    state = ObjectState(original, scope_id="plain")
    state.update_parameter("value", 2)
    cached = state.to_object()
    checkpoint = ObjectStateTransactionCheckpoint.capture(state)
    expected_parameters = dict(state.parameters)
    expected_saved_parameters = dict(state._saved_parameters)
    expected_dirty_fields = set(state.dirty_fields)
    expected_signature_diff_fields = set(state.signature_diff_fields)

    state.mark_saved()
    state.update_parameter("value", 3)
    state.update_parameter("callback", lambda value: value * 2)

    checkpoint.restore(state)

    assert state.object_instance is original
    assert state.saved_object is original
    assert state.parameters == expected_parameters
    assert state._saved_parameters == expected_saved_parameters
    assert state.parameters["callback"] is _callback
    assert state._saved_parameters["callback"] is _callback
    assert state._cached_object is cached
    assert state.is_raw_dirty is True
    assert state.dirty_fields == expected_dirty_fields
    assert state.signature_diff_fields == expected_signature_diff_fields
    assert state.to_object().callback is _callback
    assert state.to_object().value == 2


def test_checkpoint_restores_exact_delegate_and_callable_identities() -> None:
    original_delegate = CallbackConfig()
    host = DelegatedHost(original_delegate)
    state = ObjectState(host, scope_id="delegated")
    state.update_parameter("value", 2)
    checkpoint = ObjectStateTransactionCheckpoint.capture(state)

    state.mark_saved()
    replacement = CallbackConfig(value=5, callback=lambda value: value - 1)
    state.update_object_instance(replacement)

    checkpoint.restore(state)

    assert state.object_instance is host
    assert state._extraction_target is original_delegate
    assert host.config is original_delegate
    assert state.saved_object is original_delegate
    assert state.parameters["value"] == 2
    assert state.parameters["callback"] is _callback
    assert state._saved_parameters["callback"] is _callback
    assert state.is_raw_dirty is True


def test_checkpoint_emits_only_fields_whose_transaction_state_changed() -> None:
    state = ObjectState(CallbackConfig(), scope_id="notifications")
    state.update_parameter("value", 2)
    checkpoint = ObjectStateTransactionCheckpoint.capture(state)
    notifications: list[set[str]] = []
    state.on_state_changed(lambda fields: notifications.append(set(fields)))

    state.update_parameter("value", 3)
    checkpoint.restore(state)

    assert notifications[-1] == {"value"}


def test_atomic_success_failure_restores_snapshot_dirty_scopes() -> None:
    ObjectStateRegistry.clear()
    ObjectStateRegistry.mark_snapshot_dirty_scope("already-dirty")

    with pytest.raises(RuntimeError, match="transaction failed"):
        with ObjectStateRegistry.atomic_success("failing transaction"):
            ObjectStateRegistry.mark_snapshot_dirty_scope("must-not-leak")
            raise RuntimeError("transaction failed")

    assert ObjectStateRegistry._snapshot_dirty_scopes == {"already-dirty"}


def test_checkpoint_restore_handles_non_scalar_equality_results() -> None:
    class AmbiguousComparison:
        def __bool__(self) -> bool:
            raise ValueError("ambiguous")

    class AmbiguousValue:
        def __eq__(self, other) -> AmbiguousComparison:
            del other
            return AmbiguousComparison()

    state = ObjectState(CallbackConfig(), scope_id="ambiguous-equality")
    checkpoint = ObjectStateTransactionCheckpoint.capture(state)
    checkpoint.parameters["value"] = AmbiguousValue()

    checkpoint.restore(state)

    assert isinstance(state.parameters["value"], AmbiguousValue)
