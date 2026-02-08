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
