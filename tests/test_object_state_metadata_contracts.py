from __future__ import annotations

from dataclasses import dataclass

import pytest

from objectstate.object_state import ObjectState
from objectstate.object_state_metadata import (
    ObjectStateMetadataContract,
    ObjectStateMetadataContractRegistry,
)
from objectstate.object_state_registry import ObjectStateRegistry


def _reset_registry_and_history() -> None:
    ObjectStateRegistry._states.clear()
    ObjectStateRegistry._time_travel_limbo.clear()
    ObjectStateRegistry._graveyard.clear()
    ObjectStateRegistry._snapshots.clear()
    ObjectStateRegistry._timelines.clear()
    ObjectStateRegistry._current_timeline = "main"
    ObjectStateRegistry._current_head = None
    ObjectStateRegistry._in_time_travel = False
    ObjectStateRegistry._atomic_depth = 0
    ObjectStateRegistry._atomic_label = None
    ObjectStateRegistry._atomic_triggering_scope = None


@dataclass
class Dummy:
    value: int = 1


def test_namespaced_metadata_requires_registered_contract_on_write() -> None:
    state = ObjectState(Dummy(), scope_id="metadata_contract_write")

    with pytest.raises(KeyError, match="not registered"):
        state.metadata["contract_test.unregistered"] = "stale"


def test_namespaced_metadata_requires_registered_contract_on_snapshot() -> None:
    _reset_registry_and_history()
    state = ObjectState(Dummy(), scope_id="metadata_contract_snapshot")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    state.metadata = {"contract_test.injected_without_store": "stale"}

    with pytest.raises(RuntimeError, match="Cannot snapshot ObjectState metadata"):
        ObjectStateRegistry.record_snapshot("bad metadata", scope_id=state.scope_id)


def test_registered_metadata_restores_through_time_travel() -> None:
    _reset_registry_and_history()
    contract = ObjectStateMetadataContractRegistry.register(
        ObjectStateMetadataContract(
            key="contract_test.time_travel_token",
            owner="objectstate.tests",
            description="Verifies extension metadata participates in time travel.",
        )
    )
    state = ObjectState(Dummy(), scope_id="metadata_contract_restore")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    state.set_extension_metadata(contract, "before")
    ObjectStateRegistry.record_snapshot("before", scope_id=state.scope_id)
    before_id = ObjectStateRegistry.get_branch_history()[-1].id

    state.metadata[contract.key] = "after"
    ObjectStateRegistry.record_snapshot("after", scope_id=state.scope_id)

    assert ObjectStateRegistry.time_travel_to_snapshot(before_id)
    restored = ObjectStateRegistry.get_by_scope(state.scope_id)
    assert restored is state
    assert state.metadata[contract.key] == "before"
    assert contract.key in state._last_changed_meta_keys
