from __future__ import annotations

from dataclasses import dataclass

from objectstate.object_state import ObjectState
from objectstate.object_state_registry import ObjectStateRegistry


def _reset_registry_and_history() -> None:
    """Hard reset for tests.

    ObjectStateRegistry has global process-level state (registry + snapshot DAG).
    Existing test suite doesn't currently exercise history, so we reset it here.
    """
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
    x: int = 1


def test_cascade_unregister_preserves_states_for_time_travel_restore() -> None:
    _reset_registry_and_history()

    plate_scope = "/tmp/plate"
    step_scope = f"{plate_scope}::functionstep_4"
    func_scope = f"{step_scope}::function_0"

    step_state = ObjectState(Dummy(), scope_id=step_scope)
    func_state = ObjectState(Dummy(), scope_id=func_scope, parent_state=step_state)

    ObjectStateRegistry.register(step_state)
    ObjectStateRegistry.register(func_state)
    ObjectStateRegistry.record_snapshot("before delete", scope_id=step_scope)
    before_id = ObjectStateRegistry.get_branch_history()[-1].id

    # User delete path in OpenHCS uses cascade unregister for step + descendants.
    ObjectStateRegistry.unregister_scope_and_descendants(step_scope)

    # Undo should resurrect both scopes.
    ok = ObjectStateRegistry.time_travel_to_snapshot(before_id)
    assert ok
    assert ObjectStateRegistry.get_by_scope(step_scope) is not None
    assert ObjectStateRegistry.get_by_scope(func_scope) is not None


def test_atomic_snapshot_keeps_first_scoped_mutation_owner() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    sibling_scope = "/tmp/plate::functionstep_9"
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    sibling_state = ObjectState(Dummy(), scope_id=sibling_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)
    ObjectStateRegistry.register(sibling_state, _skip_snapshot=True)

    with ObjectStateRegistry.atomic("edit step"):
        step_state.update_parameter("x", 2)
        sibling_state.update_parameter("x", 3)

    snapshot = ObjectStateRegistry.get_branch_history()[-1]
    assert snapshot.triggering_scope == step_scope


def test_atomic_snapshot_uses_explicit_mutation_owner() -> None:
    _reset_registry_and_history()

    pipeline_scope = "/tmp/plate::pipeline"
    step_scope = "/tmp/plate::functionstep_5"
    pipeline_state = ObjectState(Dummy(), scope_id=pipeline_scope)
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    ObjectStateRegistry.register(pipeline_state, _skip_snapshot=True)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    with ObjectStateRegistry.atomic("edit step", scope_id=step_scope):
        pipeline_state.update_parameter("x", 2)

    snapshot = ObjectStateRegistry.get_branch_history()[-1]
    assert snapshot.triggering_scope == step_scope


def test_raw_dirty_transition_notifies_when_resolved_dirty_is_unchanged() -> None:
    _reset_registry_and_history()

    state = ObjectState(Dummy(), scope_id="raw-dirty")
    state._live_resolved = {"x": 1}
    state._saved_resolved = {"x": 1}
    state._dirty_fields = set()
    state._raw_dirty = False

    notifications = []
    state.on_state_changed(lambda: notifications.append(state.is_raw_dirty))

    state.parameters["x"] = 2
    state._sync_materialized_state()
    state.parameters["x"] = state._saved_parameters["x"]
    state._sync_materialized_state()

    assert notifications == [True, False]
    assert state.dirty_fields == set()
    assert not state.is_raw_dirty
