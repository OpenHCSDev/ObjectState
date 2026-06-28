"""ObjectState replacement lifecycle tests."""

from dataclasses import dataclass

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    get_live_global_config,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)


def _reset_registry() -> None:
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
    ObjectStateRegistry._token = 0


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    _reset_registry()
    yield
    _reset_registry()


@dataclass
class PlainConfig:
    threshold: int = 1
    label: str = "old"


class DelegatedHost:
    __objectstate_delegate__ = "config"

    def __init__(self, config: PlainConfig) -> None:
        self.config = config


def test_update_object_instance_notifies_resolved_changes_and_saved_baseline():
    state = ObjectState(PlainConfig(), scope_id="config")
    changed_events: list[set[str]] = []
    state.on_resolved_changed(lambda changed: changed_events.append(set(changed)))

    state.update_object_instance(PlainConfig(threshold=2))

    assert changed_events == [{"threshold"}]
    assert state.get_resolved_value("threshold") == 2
    assert state.get_saved_resolved_value("threshold") == 2
    assert state.dirty_fields == set()
    assert state.is_raw_dirty is False
    assert state.last_changed_field == "threshold"


def test_delegate_replacement_refreshes_saved_resolved_and_default_diff():
    host = DelegatedHost(PlainConfig())
    state = ObjectState(host, scope_id="host")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    host.config = PlainConfig(threshold=2)

    assert state.get_resolved_value("threshold") == 2
    assert state.get_saved_resolved_value("threshold") == 2
    assert state.dirty_fields == set()
    assert state.signature_diff_fields == {"threshold"}

    state.update_parameter("threshold", 3)
    assert state.dirty_fields == {"threshold"}
    assert state.signature_diff_fields == {"threshold"}

    state.update_parameter("threshold", 2)
    assert state.dirty_fields == set()
    assert state.signature_diff_fields == {"threshold"}


def test_global_update_object_instance_refreshes_inherited_descendants():
    @dataclass
    class GlobalConfig:
        threshold: int = 1

    mark_global_config_type(GlobalConfig)
    set_base_config_type(GlobalConfig)
    LazyGlobalConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)

    set_global_config_for_editing(GlobalConfig, GlobalConfig(threshold=1))
    global_state = ObjectState(GlobalConfig(threshold=1), scope_id="")
    child_state = ObjectState(LazyGlobalConfig(), scope_id="plate::step")
    ObjectStateRegistry.register(global_state, _skip_snapshot=True)
    ObjectStateRegistry.register(child_state, _skip_snapshot=True)
    child_events: list[set[str]] = []
    child_state.on_resolved_changed(lambda changed: child_events.append(set(changed)))

    assert child_state.get_resolved_value("threshold") == 1

    global_state.update_object_instance(GlobalConfig(threshold=7))

    assert get_live_global_config(GlobalConfig).threshold == 7
    assert child_state.get_resolved_value("threshold") == 7
    assert child_state.get_saved_resolved_value("threshold") == 7
    assert {"threshold"} in child_events
    assert child_state.dirty_fields == set()


class CallableHolder:
    def __init__(self, operation=None):
        self.operation = operation


def _operation(image=None):
    return image


def test_callable_baseline_normalization_is_field_name_independent():
    state = ObjectState(CallableHolder(operation=_operation), scope_id="callable")

    state.update_parameter("operation", [(_operation, {"unused": None})])

    assert state.dirty_fields == set()
