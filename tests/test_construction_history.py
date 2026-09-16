"""Native construction/history ownership across fresh registries and branches."""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    get_live_global_config,
    get_saved_global_config,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)
from objectstate.history_migration import HistoryMigration


@dataclass
class Config:
    value: int | None = None
    items: list[int] | None = None
    excluded: str = "retained"


@dataclass
class OtherConfig:
    weight: float = 0.25


@dataclass
class ContextConfig:
    threshold: int = 1


# Bind the native generated declaration in its declared module, just as normal
# application config declarations do. Do not serialize factory closure locals.
LazyContextConfig = LazyDataclassFactory.make_lazy_simple(ContextConfig)


class Lifecycle:
    __objectstate_delegate__ = "config"

    def __init__(self, config: Config):
        self.config = config
        self.resource = object()

    def __getstate__(self):
        raise AssertionError("Application lifecycle resources must never be serialized")


class RejectingLifecycle:
    __objectstate_delegate__ = "config"

    def __init__(self, config):
        self._config = config

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, config):
        if config.value == 99:
            raise ValueError("Rejected application attachment")
        self._config = config


def first_callable(image=None, threshold: float = 1.0):
    return image


def second_callable(image=None, weights=None):
    return image


def equal_signature_callable(image=None, threshold: float = 1.0):
    return image


@pytest.fixture(autouse=True)
def clean_registry():
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


def register(target, scope: str, **kwargs):
    state = ObjectState(target, scope_id=scope, **kwargs)
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    return state


def record(label: str) -> str:
    ObjectStateRegistry.record_snapshot(label)
    return ObjectStateRegistry.get_branch_history()[-1].id


def test_fresh_load_constructs_absent_scopes_and_exact_parent_exclusions(
    tmp_path: Path,
):
    parent = register(Config(value=7), "z-parent")
    child = register(
        Config(value=None), "a-child", parent_state=parent, exclude_params=["excluded"]
    )
    before = record("parent and child")
    path = tmp_path / "complete.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    ObjectStateRegistry.clear()
    events = []
    subscription = ObjectStateRegistry.add_register_callback(
        lambda scope, state: events.append(
            (scope, state._parent_state, set(ObjectStateRegistry._states))
        )
    )
    try:
        ObjectStateRegistry.load_history_from_file(str(path))
    finally:
        subscription.release()
    restored_parent = ObjectStateRegistry.get_by_scope("z-parent")
    restored_child = ObjectStateRegistry.get_by_scope("a-child")
    assert restored_child._parent_state is restored_parent
    assert restored_child._exclude_param_names == ["excluded"]
    assert restored_child.to_object().excluded == child.to_object().excluded
    assert restored_child.parameters["value"] is None
    assert restored_child._saved_parameters["value"] is None
    assert {entry[0] for entry in events} == {"z-parent", "a-child"}
    assert all(entry[2] == {"z-parent", "a-child"} for entry in events)
    assert ObjectStateRegistry._snapshots[before].all_states.keys() == {
        "z-parent",
        "a-child",
    }


def test_same_scope_callable_owner_and_schema_restore_without_replacing_state():
    state = register(first_callable, "callable")
    first = record("first callable")
    state.update_object_instance(second_callable)
    second = record("second callable")
    for snapshot, function, parameters in (
        (first, first_callable, {"image", "threshold"}),
        (second, second_callable, {"image", "weights"}),
        (first, first_callable, {"image", "threshold"}),
    ):
        assert ObjectStateRegistry.time_travel_to_snapshot(snapshot)
        assert ObjectStateRegistry.get_by_scope("callable") is state
        assert state.object_instance is function
        assert set(state.parameters) == parameters
        assert set(state._signature_defaults) == parameters
        assert set(state._path_to_type) == parameters


def test_equal_signature_owner_change_records_and_notifies_without_fake_value_changes():
    state = register(first_callable, "same-signature")
    initial = record("first declaration")
    with ObjectStateRegistry.atomic("replace declaration with equal signature"):
        state.update_object_instance(equal_signature_callable)
    history = ObjectStateRegistry.get_branch_history()
    assert len(history) == 2
    replacement = history[-1].id
    with ObjectStateRegistry.atomic("true no-op"):
        pass
    assert len(ObjectStateRegistry.get_branch_history()) == 2
    events = []
    values = []
    completed = []
    state.on_state_changed(
        lambda fields: events.append((state.object_instance, fields))
    )
    state.on_resolved_changed(lambda fields: values.append(fields))
    subscription = ObjectStateRegistry.add_time_travel_complete_callback(
        lambda entries, trigger: completed.append(entries)
    )
    try:
        for snapshot, target in (
            (initial, first_callable),
            (replacement, equal_signature_callable),
        ):
            assert ObjectStateRegistry.time_travel_to_snapshot(snapshot)
            assert state.object_instance is target
            assert events[-1] == (target, set())
            assert completed[-1] == [("same-signature", state)]
    finally:
        subscription.release()
    assert len(events) == 2
    assert values == []


def test_same_scope_registered_replacement_captures_exact_owner_with_equal_parameters():
    initial_state = register(first_callable, "registered-owner")
    initial = record("original registered owner")
    with ObjectStateRegistry.atomic("replace registered owner"):
        replacement_state = register(equal_signature_callable, "registered-owner")
    replacement = ObjectStateRegistry.get_branch_history()[-1].id
    assert (
        ObjectStateRegistry._snapshots[replacement]
        .all_states["registered-owner"]
        .construction.target
        is equal_signature_callable
    )
    assert ObjectStateRegistry.time_travel_to_snapshot(initial)
    assert ObjectStateRegistry.get_by_scope("registered-owner") is replacement_state
    assert replacement_state.object_instance is first_callable
    assert ObjectStateRegistry.time_travel_to_snapshot(replacement)
    assert replacement_state.object_instance is equal_signature_callable
    assert initial_state is not replacement_state


def test_alias_graph_is_detached_and_restored_across_scopes_and_saved_live(
    tmp_path: Path,
):
    shared = [3, 5]
    first = register(Config(items=shared), "first")
    second = register(Config(items=shared), "second")
    for state in (first, second):
        state._saved_parameters["items"] = shared
        state._live_resolved["items"] = shared
        state._saved_resolved["items"] = shared
    baseline = record("shared graph")
    original = ObjectStateRegistry._snapshots[baseline]
    first.update_parameter("value", 9)
    edited = ObjectStateRegistry.get_branch_history()[-1]
    assert edited.all_states["second"] is not original.all_states["second"]
    shared.append(8)
    assert original.all_states["first"].parameters["items"] == [3, 5]
    path = tmp_path / "aliases.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    ObjectStateRegistry.clear()
    ObjectStateRegistry.load_history_from_file(str(path))
    assert ObjectStateRegistry.time_travel_to_snapshot(baseline)
    first = ObjectStateRegistry.get_by_scope("first")
    second = ObjectStateRegistry.get_by_scope("second")
    value = first.parameters["items"]
    assert value is second.parameters["items"]
    assert value is first._saved_parameters["items"]
    assert value is first._live_resolved["items"]
    assert value is first._saved_resolved["items"]
    assert value is first.object_instance.items
    assert value is second.object_instance.items
    value.append(99)
    assert original.all_states["first"].parameters["items"] == [3, 5]
    assert ObjectStateRegistry._snapshots[baseline].all_states["first"].parameters[
        "items"
    ] == [3, 5]


def test_delegated_lifecycle_retained_but_never_persisted(tmp_path: Path):
    wrapper = Lifecycle(Config(value=2))
    state = register(wrapper, "delegated")
    initial = record("delegated initial")
    state.update_object_instance(Config(value=8))
    current = record("delegated replacement")
    path = tmp_path / "delegated.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    resource = wrapper.resource
    ObjectStateRegistry.load_history_from_file(str(path))
    assert ObjectStateRegistry.get_by_scope("delegated") is state
    assert state.object_instance is wrapper
    assert wrapper.resource is resource
    assert wrapper.config.value == 8
    assert ObjectStateRegistry.time_travel_to_snapshot(initial)
    assert wrapper.config.value == 2
    assert ObjectStateRegistry.time_travel_to_snapshot(current)
    assert wrapper.config.value == 8


@pytest.mark.parametrize(
    "damage", ["absent-delegate", "legacy", "missing-parent", "cycle"]
)
def test_invalid_import_fails_closed_before_history_registry_or_callbacks_change(
    damage: str,
):
    register(Lifecycle(Config(value=2)), "delegated")
    register(Config(value=4), "direct")
    snapshot_id = record("valid graph")
    payload = ObjectStateRegistry.export_history_to_dict()
    if damage == "absent-delegate":
        ObjectStateRegistry.clear()
        register(Config(value=17), "unrelated")
        record("unrelated retained")
    elif damage == "legacy":
        payload.pop("format_version")
    else:
        state = payload["snapshots"][snapshot_id]["states"]["direct"]
        state["construction"] = replace(
            state["construction"],
            parent_scope="missing" if damage == "missing-parent" else "direct",
        )
    states = dict(ObjectStateRegistry._states)
    snapshots = ObjectStateRegistry._snapshots
    timelines = ObjectStateRegistry._timelines
    dirty = set(ObjectStateRegistry._snapshot_dirty_scopes)
    head = ObjectStateRegistry._current_head
    events = []
    subscriptions = [
        ObjectStateRegistry.add_register_callback(lambda *args: events.append(args)),
        ObjectStateRegistry.add_unregister_callback(lambda *args: events.append(args)),
        ObjectStateRegistry.add_history_changed_callback(
            lambda: events.append("history")
        ),
    ]
    try:
        with pytest.raises(ValueError):
            ObjectStateRegistry.import_history_from_dict(payload)
    finally:
        for subscription in subscriptions:
            subscription.release()
    assert ObjectStateRegistry._states == states
    assert ObjectStateRegistry._snapshots is snapshots
    assert ObjectStateRegistry._timelines is timelines
    assert ObjectStateRegistry._snapshot_dirty_scopes == dirty
    assert ObjectStateRegistry._current_head == head
    assert events == []


def test_branch_navigation_restores_distinct_declarations_and_historical_scopes(
    tmp_path: Path,
):
    state = register(Config(value=None), "shared-scope")
    initial = record("initial")
    state.update_object_instance(OtherConfig(weight=0.8))
    register(Config(value=12), "future-only")
    future = record("future")
    assert ObjectStateRegistry.time_travel_to_snapshot(initial)
    state.update_object_instance(Config(value=5))
    branch = record("diverged")
    path = tmp_path / "branches.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    ObjectStateRegistry.clear()
    ObjectStateRegistry.load_history_from_file(str(path))
    for snapshot, target_type, scopes in (
        (future, OtherConfig, {"shared-scope", "future-only"}),
        (initial, Config, {"shared-scope"}),
        (branch, Config, {"shared-scope"}),
    ):
        assert ObjectStateRegistry.time_travel_to_snapshot(snapshot)
        assert (
            type(ObjectStateRegistry.get_by_scope("shared-scope").object_instance)
            is target_type
        )
        assert set(ObjectStateRegistry._states) == scopes


def test_history_restores_saved_live_global_context_after_real_invalidation(
    tmp_path: Path,
):
    mark_global_config_type(ContextConfig)
    set_base_config_type(ContextConfig)
    target = ContextConfig(threshold=3)
    set_global_config_for_editing(ContextConfig, target)
    parent = ObjectState(target, scope_id=None)
    ObjectStateRegistry.register(parent, _skip_snapshot=True)
    child = register(LazyContextConfig(), "child", parent_state=parent)
    child._parent_field_name = "threshold"
    initial = record("global parent")
    parent.update_parameter("threshold", 9)
    edited = ObjectStateRegistry.get_branch_history()[-1].id
    path = tmp_path / "contexts.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    ObjectStateRegistry.clear()
    set_global_config_for_editing(ContextConfig, ContextConfig(threshold=77))
    ObjectStateRegistry.load_history_from_file(str(path))
    for snapshot, live in ((initial, 3), (edited, 9), (initial, 3)):
        assert ObjectStateRegistry.time_travel_to_snapshot(snapshot)
        parent = ObjectStateRegistry.get_by_scope(None)
        child = ObjectStateRegistry.get_by_scope("child")
        assert child._parent_state is parent
        assert child._parent_field_name == "threshold"
        assert child.parameters["threshold"] is None
        assert child._saved_parameters["threshold"] is None
        assert get_saved_global_config(ContextConfig).threshold == 3
        assert get_live_global_config(ContextConfig).threshold == live
        child.invalidate_cache()
        assert child.get_resolved_value("threshold") == live
        assert child._compute_resolved_snapshot(use_saved=True)["threshold"] == 3


def test_failed_attachment_rolls_back_complete_graph_and_loaded_history(tmp_path: Path):
    shared = [1, 2]
    direct = register(Config(value=4, items=shared), "a-direct")
    wrapper = RejectingLifecycle(Config(value=2, items=shared))
    delegated = register(wrapper, "z-delegated")
    extra = register(Config(value=6), "extra-current")
    snapshot_id = record("original complete graph")
    original = ObjectStateRegistry._snapshots[snapshot_id]
    bad_states = dict(original.all_states)
    bad_states.pop("extra-current")
    for scope, value in (("a-direct", 31), ("z-delegated", 99)):
        state = bad_states[scope]
        bad_states[scope] = replace(
            state,
            construction=replace(
                state.construction, target=Config(value=value, items=[1, 2])
            ),
            parameters={**state.parameters, "value": value},
            saved_parameters={**state.saved_parameters, "value": value},
            live_resolved={**state.live_resolved, "value": value},
            saved_resolved={**state.saved_resolved, "value": value},
        )
    histories = ObjectStateRegistry._snapshots
    ObjectStateRegistry._snapshots = {
        **histories,
        snapshot_id: replace(original, all_states=bad_states),
    }
    path = tmp_path / "rejecting.objectstate"
    ObjectStateRegistry.save_history_to_file(str(path))
    ObjectStateRegistry._snapshots = histories
    file_bytes = path.read_bytes()
    raw = direct.parameters
    target = direct.object_instance
    delegate_target = wrapper.config
    timelines = ObjectStateRegistry._timelines
    events = []
    subscriptions = [
        ObjectStateRegistry.add_register_callback(lambda *args: events.append(args)),
        ObjectStateRegistry.add_unregister_callback(lambda *args: events.append(args)),
        ObjectStateRegistry.add_history_changed_callback(
            lambda: events.append("history")
        ),
    ]
    try:
        with pytest.raises(ValueError, match="Rejected application attachment"):
            ObjectStateRegistry.load_history_from_file(str(path))
    finally:
        for subscription in subscriptions:
            subscription.release()
    assert ObjectStateRegistry._snapshots is histories
    assert ObjectStateRegistry._timelines is timelines
    assert ObjectStateRegistry._current_head is None
    assert ObjectStateRegistry._states == {
        "a-direct": direct,
        "z-delegated": delegated,
        "extra-current": extra,
    }
    assert direct.parameters is raw
    assert direct.object_instance is target
    assert direct.parameters["items"] is shared
    assert delegated.object_instance is wrapper
    assert wrapper.config is delegate_target
    assert direct.object_instance.items is wrapper.config.items is shared
    assert events == []
    assert path.read_bytes() == file_bytes


def test_explicit_migration_receives_one_detached_alias_graph_and_must_return_v2():
    shared = [1]
    state = register(Config(items=shared), "direct")
    record("migration input")
    document = ObjectStateRegistry.export_history_to_dict()
    document["format_version"] = 1
    document["source_alias"] = shared

    class FixtureMigration(HistoryMigration):
        def migrate(self, document, constructions):
            assert document["source_alias"] is constructions["direct"].target.items
            document["source_alias"].append(7)
            document["format_version"] = 2
            return document

    ObjectStateRegistry.import_history_from_dict(document, migration=FixtureMigration())
    assert document["format_version"] == 1
    assert document["source_alias"] == shared == [1]
    assert state.object_instance.items is shared
