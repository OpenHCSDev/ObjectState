from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from objectstate.object_state import ObjectState
from objectstate.object_state_registry import (
    ObjectStateRegistry,
    TimeTravelChangeSet,
    TimeTravelScopeChange,
)


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
    ObjectStateRegistry._atomic_snapshot_requested = False
    ObjectStateRegistry._atomic_entry_signature = None


@dataclass
class Dummy:
    x: int = 1


@dataclass(frozen=True)
class StructuralRoot:
    child_scope_ids: tuple[str, ...]


class FilterSubject(Enum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class FilterClause:
    subject: FilterSubject
    value: str


@dataclass(frozen=True)
class FilterConfig:
    filters: tuple[FilterClause, ...] | None = None


@dataclass(frozen=True)
class StepWithFilterConfig:
    config: FilterConfig = FilterConfig(
        filters=(FilterClause(FilterSubject.FILE, "w1"),)
    )


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


def test_structural_registration_does_not_create_user_snapshots() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_4"
    func_scope = f"{step_scope}::function_0"
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    func_state = ObjectState(Dummy(), scope_id=func_scope, parent_state=step_state)

    ObjectStateRegistry.register(step_state)
    ObjectStateRegistry.register(func_state)
    ObjectStateRegistry.unregister_scope_and_descendants(step_scope)

    assert ObjectStateRegistry.get_branch_history() == []


def test_noop_atomic_does_not_create_user_snapshot() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    with ObjectStateRegistry.atomic("edit step", scope_id=step_scope):
        step_state.update_parameter("x", 1)

    assert ObjectStateRegistry.get_branch_history() == []


def test_structural_atomic_records_registry_membership_change() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"

    with ObjectStateRegistry.atomic("add step", scope_id=step_scope):
        ObjectStateRegistry.register(ObjectState(Dummy(), scope_id=step_scope))

    snapshots = ObjectStateRegistry.get_branch_history()
    assert len(snapshots) == 1
    assert snapshots[0].label == f"add step [{step_scope}]"
    assert snapshots[0].triggering_scope == step_scope


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


def test_first_parameter_edit_baseline_precedes_mutation() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    step_state.update_parameter("x", 2)

    history = ObjectStateRegistry.get_branch_history()
    assert [snapshot.label for snapshot in history] == [
        "init",
        f"edit x [{step_scope}]",
    ]

    assert ObjectStateRegistry.time_travel_to_snapshot(history[0].id)
    assert step_state.parameters["x"] == 1
    assert ObjectStateRegistry.time_travel_to_snapshot(history[1].id)
    assert step_state.parameters["x"] == 2


def test_time_travel_back_and_forward_report_transition_owner() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(Dummy(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    step_state.update_parameter("x", 2)
    history = ObjectStateRegistry.get_branch_history()
    assert [snapshot.triggering_scope for snapshot in history] == [None, step_scope]

    observed_triggers: list[str | None] = []

    def record_trigger(_dirty_states, triggering_scope: str | None) -> None:
        observed_triggers.append(triggering_scope)

    ObjectStateRegistry.add_time_travel_complete_callback(record_trigger)
    try:
        assert ObjectStateRegistry.time_travel_back()
        assert step_state.parameters["x"] == 1
        assert observed_triggers[-1] == step_scope

        assert ObjectStateRegistry.time_travel_forward()
        assert step_state.parameters["x"] == 2
        assert observed_triggers[-1] == step_scope
    finally:
        ObjectStateRegistry.remove_time_travel_complete_callback(record_trigger)


def test_time_travel_callback_entries_include_nested_resolved_path_changes() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    change_set = TimeTravelChangeSet(
        triggering_scope=step_scope,
        scope_changes={
            step_scope: TimeTravelScopeChange(
                changed_paths={"config.filters"},
                changed_param_keys=set(),
                meta_changed_keys=set(),
                is_concrete_dirty=False,
            ),
        },
    )

    assert change_set.legacy_entries(ObjectStateRegistry._states) == [
        (step_scope, step_state)
    ]


def test_time_travel_invalidates_cached_reconstructed_object() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)
    ObjectStateRegistry.ensure_baseline_snapshot()

    step_state.update_parameter(
        "config.filters",
        (FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),),
    )
    edited_step = step_state.to_object()
    assert edited_step.config.filters == (
        FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),
    )

    history = ObjectStateRegistry.get_branch_history()
    assert ObjectStateRegistry.time_travel_to_snapshot(history[0].id)

    restored_step = step_state.to_object()
    assert restored_step.config.filters == (
        FilterClause(FilterSubject.FILE, "w1"),
    )
    assert step_state.parameters["config.filters"] == (
        FilterClause(FilterSubject.FILE, "w1"),
    )


def test_child_edit_rebuilds_dataclass_parent_for_snapshot_restore() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    edited_filters = (FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),)
    step_state.update_parameter("config.filters", edited_filters)

    assert step_state.parameters["config.filters"] == edited_filters
    assert step_state.parameters["config"].filters == edited_filters
    assert step_state.to_object().config.filters == edited_filters

    history = ObjectStateRegistry.get_branch_history()
    assert [snapshot.label for snapshot in history] == [
        "init",
        f"edit config.filters [{step_scope}]",
    ]
    edited_snapshot = history[-1]
    edited_snapshot_state = edited_snapshot.all_states[step_scope]
    assert edited_snapshot_state.parameters["config.filters"] == edited_filters
    assert edited_snapshot_state.parameters["config"].filters == edited_filters

    assert ObjectStateRegistry.time_travel_back()
    restored_filters = (FilterClause(FilterSubject.FILE, "w1"),)
    assert step_state.parameters["config.filters"] == restored_filters
    assert step_state.parameters["config"].filters == restored_filters

    assert ObjectStateRegistry.time_travel_forward()
    assert step_state.parameters["config.filters"] == edited_filters
    assert step_state.parameters["config"].filters == edited_filters


def test_container_edit_records_child_snapshot_for_time_travel() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)
    changed_notifications: list[set[str]] = []
    step_state.on_resolved_changed(
        lambda changed_paths: changed_notifications.append(set(changed_paths))
    )

    step_state.update_parameter(
        "config",
        FilterConfig(
            filters=(FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),),
        ),
    )

    changed_paths = set().union(*changed_notifications)
    assert "config.filters[0].subject" in changed_paths
    assert "config.filters[0].value" in changed_paths
    assert step_state.last_changed_field == "config.filters[0].subject"
    history = ObjectStateRegistry.get_branch_history()
    assert [snapshot.label for snapshot in history] == [
        "init",
        f"edit config.filters [{step_scope}]",
    ]

    assert ObjectStateRegistry.time_travel_back()
    assert step_state.parameters["config.filters"] == (
        FilterClause(FilterSubject.FILE, "w1"),
    )
    assert step_state.last_changed_field == "config.filters[0].subject"

    assert ObjectStateRegistry.time_travel_forward()
    assert step_state.parameters["config.filters"] == (
        FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),
    )
    assert step_state.last_changed_field == "config.filters[0].subject"


def test_time_travel_emits_single_resolved_and_state_notification() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    step_state.update_parameter(
        "config.filters",
        (FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),),
    )

    resolved_notifications: list[set[str]] = []
    state_notifications: list[set[str]] = []
    step_state.on_resolved_changed(
        lambda changed_paths: resolved_notifications.append(set(changed_paths))
    )
    step_state.on_state_changed(
        lambda _changed_paths: state_notifications.append(set(step_state.dirty_fields))
    )

    assert ObjectStateRegistry.time_travel_back()

    assert resolved_notifications == [
        {
            "config.filters",
            "config.filters[0].subject",
            "config.filters[0].value",
        }
    ]
    assert state_notifications == [set()]
    assert step_state.parameters["config.filters"] == (
        FilterClause(FilterSubject.FILE, "w1"),
    )


def test_time_travel_skips_snapshot_apply_for_unchanged_scope(monkeypatch) -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    sibling_scope = "/tmp/plate::functionstep_9"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    sibling_state = ObjectState(Dummy(), scope_id=sibling_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)
    ObjectStateRegistry.register(sibling_state, _skip_snapshot=True)

    step_state.update_parameter(
        "config",
        FilterConfig(
            filters=(FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),),
        ),
    )
    history = ObjectStateRegistry.get_branch_history()

    sibling_state._last_changed_field = "x"
    sibling_state._last_changed_paths = {"x"}
    sibling_state._last_changed_values = {"x": (1, 2)}
    applied_to_sibling = []
    original_sync = sibling_state._sync_materialized_state

    def record_sync(*args, **kwargs):
        applied_to_sibling.append(True)
        return original_sync(*args, **kwargs)

    monkeypatch.setattr(sibling_state, "_sync_materialized_state", record_sync)

    assert ObjectStateRegistry.time_travel_to_snapshot(history[0].id)
    assert applied_to_sibling == []
    assert sibling_state.last_changed_field is None


def test_container_edit_notifies_when_dirty_status_is_unchanged() -> None:
    _reset_registry_and_history()

    step_scope = "/tmp/plate::functionstep_5"
    step_state = ObjectState(StepWithFilterConfig(), scope_id=step_scope)
    ObjectStateRegistry.register(step_state, _skip_snapshot=True)

    step_state.update_parameter(
        "config",
        FilterConfig(
            filters=(FilterClause(FilterSubject.DIRECTORY, "TimePoint_1"),),
        ),
    )
    changed_notifications: list[set[str]] = []
    step_state.on_resolved_changed(
        lambda changed_paths: changed_notifications.append(set(changed_paths))
    )

    step_state.update_parameter(
        "config",
        FilterConfig(
            filters=(FilterClause(FilterSubject.DIRECTORY, "TimePoint_2"),),
        ),
    )

    changed_paths = set().union(*changed_notifications)
    assert "config.filters[0].value" in changed_paths
    assert step_state.last_changed_field == "config.filters[0].value"
    assert step_state.dirty_fields == {"config.filters"}


def test_raw_dirty_transition_notifies_when_resolved_dirty_is_unchanged() -> None:
    _reset_registry_and_history()

    state = ObjectState(Dummy(), scope_id="raw-dirty")
    state._live_resolved = {"x": 1}
    state._saved_resolved = {"x": 1}
    state._dirty_fields = set()
    state._raw_dirty = False

    notifications = []
    state.on_state_changed(lambda _changed_paths: notifications.append(state.is_raw_dirty))

    state.parameters["x"] = 2
    state._sync_materialized_state()
    state.parameters["x"] = state._saved_parameters["x"]
    state._sync_materialized_state()

    assert notifications == [True, False]
    assert state.dirty_fields == set()
    assert not state.is_raw_dirty


def test_snapshot_capture_does_not_recompute_clean_unrelated_states() -> None:
    _reset_registry_and_history()

    edited_state = ObjectState(Dummy(), scope_id="edited")
    clean_state = ObjectState(Dummy(), scope_id="clean")
    ObjectStateRegistry.register(edited_state, _skip_snapshot=True)
    ObjectStateRegistry.register(clean_state, _skip_snapshot=True)
    ObjectStateRegistry.ensure_baseline_snapshot()

    def fail_clean_resolution(*_args, **_kwargs):
        raise AssertionError("clean state should not be recomputed for snapshot capture")

    clean_state._compute_resolved_snapshot = fail_clean_resolution  # type: ignore[method-assign]

    edited_state.update_parameter("x", 2)

    history = ObjectStateRegistry.get_branch_history()
    assert [snapshot.label for snapshot in history] == [
        "init",
        "edit x [edited]",
    ]
    assert history[-1].all_states["clean"].live_resolved == {"x": 1}


def test_snapshot_capture_reuses_unchanged_scope_snapshots() -> None:
    _reset_registry_and_history()

    edited_state = ObjectState(Dummy(), scope_id="edited")
    clean_state = ObjectState(Dummy(), scope_id="clean")
    ObjectStateRegistry.register(edited_state, _skip_snapshot=True)
    ObjectStateRegistry.register(clean_state, _skip_snapshot=True)
    ObjectStateRegistry.ensure_baseline_snapshot()

    baseline = ObjectStateRegistry.get_branch_history()[-1]

    edited_state.update_parameter("x", 2)

    snapshot = ObjectStateRegistry.get_branch_history()[-1]
    assert snapshot.all_states["clean"] is baseline.all_states["clean"]
    assert snapshot.all_states["edited"] is not baseline.all_states["edited"]


def test_clean_instance_replacement_is_captured_for_time_travel() -> None:
    _reset_registry_and_history()

    root_scope = "/tmp/plate::root"
    root_state = ObjectState(StructuralRoot(child_scope_ids=()), scope_id=root_scope)
    ObjectStateRegistry.register(root_state, _skip_snapshot=True)
    ObjectStateRegistry.ensure_baseline_snapshot()

    with ObjectStateRegistry.atomic("replace clean declaration", scope_id=root_scope):
        root_state.update_object_instance(
            StructuralRoot(child_scope_ids=("child_0", "child_1"))
        )

    history = ObjectStateRegistry.get_branch_history()
    assert len(history) == 2
    assert history[-1].all_states[root_scope].parameters["child_scope_ids"] == (
        "child_0",
        "child_1",
    )

    assert ObjectStateRegistry.time_travel_to_snapshot(history[0].id)
    assert root_state.to_object().child_scope_ids == ()
    assert ObjectStateRegistry.time_travel_to_snapshot(history[1].id)
    assert root_state.to_object().child_scope_ids == ("child_0", "child_1")


def test_snapshot_mapping_reuses_parent_entries_but_copies_changed_values() -> None:
    parent = {
        "unchanged": [1],
        "changed": [2],
    }
    current = {
        "unchanged": [1],
        "changed": [3],
    }

    snapshot = ObjectStateRegistry._copy_snapshot_mapping_with_parent_sharing(
        current,
        parent,
    )

    assert snapshot["unchanged"] is parent["unchanged"]
    assert snapshot["changed"] == [3]
    assert snapshot["changed"] is not current["changed"]
