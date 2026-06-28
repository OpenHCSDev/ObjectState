"""Tests for callable identity handling in ObjectState baselines."""

from typing import ClassVar

from objectstate import ObjectState, ObjectStateRegistry


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


class RebuiltCallable:
    """Callable wrapper whose deepcopy would otherwise create a new identity."""

    def __call__(self, image=None):
        return image

    def __reduce__(self):
        return (RebuiltCallable, ())


class StepLike:
    """Minimal step-shaped object with a callable declaration field."""

    callable_parameter_name: ClassVar[str] = "func"

    def __init__(self, func=None, name="step"):
        self.func = func
        self.name = name

    @classmethod
    def callable_parameter(cls) -> str:
        return cls.callable_parameter_name


def _threshold_function(image=None, threshold: float = 1.0):
    """Threshold an image."""
    return image


def test_function_parameter_paths_record_callable_owner():
    state = ObjectState(_threshold_function, scope_id="plate::step::function_0")

    assert state.type_for_path("threshold") is _threshold_function
    assert state.get_resolved_value("threshold") == 1.0


def test_saved_baseline_preserves_callable_identity_values():
    func = RebuiltCallable()

    state = ObjectState(StepLike(func=func), scope_id="plate::step")

    assert state._saved_parameters[StepLike.callable_parameter()] is func
    assert state.dirty_fields == set()
    assert state.is_raw_dirty is False


def test_time_travel_preserves_clean_callable_identity_baseline():
    _reset_registry_and_history()
    state = ObjectState(StepLike(func=RebuiltCallable()), scope_id="plate::step")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    ObjectStateRegistry.record_snapshot("clean", scope_id=state.scope_id)
    clean_id = ObjectStateRegistry.get_branch_history()[-1].id
    snapshot_state = ObjectStateRegistry._snapshots[clean_id].all_states[state.scope_id]
    callable_parameter = StepLike.callable_parameter()
    assert (
        snapshot_state.parameters[callable_parameter]
        is snapshot_state.saved_parameters[callable_parameter]
    )

    state.update_parameter("name", "changed")
    assert state.is_raw_dirty is True

    assert ObjectStateRegistry.time_travel_to_snapshot(clean_id)
    assert state.parameters[callable_parameter] is state._saved_parameters[callable_parameter]
    assert state.is_raw_dirty is False
