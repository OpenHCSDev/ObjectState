"""ObjectState replacement lifecycle tests."""

from dataclasses import dataclass, field
from typing import Annotated

import pytest
from annotated_types import Gt
from python_introspect import AnnotatedDataclassValidationMixin

from objectstate import (
    DottedFieldPath,
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
    ObjectStateRegistry._resolved_changed_callbacks.clear()


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    _reset_registry()
    yield
    _reset_registry()


@dataclass
class PlainConfig:
    threshold: int = 1
    label: str = "old"


@dataclass(frozen=True)
class DataclassLeaf:
    name: str


@dataclass
class ConfigWithDataclassLeaf:
    leaf: DataclassLeaf | None = None


@dataclass
class NestedTopology:
    threshold: int = 1
    label: str = "nested"


@dataclass
class ConfigWithNestedTopology:
    enabled: bool = True
    nested: NestedTopology = field(default_factory=NestedTopology)


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


def test_direct_parameter_paths_project_canonical_flat_topology_without_values():
    state = ObjectState(ConfigWithNestedTopology(), scope_id="config")

    assert state.direct_parameter_paths() == (
        DottedFieldPath("enabled"),
        DottedFieldPath("nested"),
    )
    assert state.direct_parameter_paths("nested") == (
        DottedFieldPath("nested.threshold"),
        DottedFieldPath("nested.label"),
    )
    assert state.direct_parameter_paths("nested.threshold") == ()
    assert state.has_parameter_descendants("nested") is True
    assert state.has_parameter_descendants("nested.threshold") is False

    state.update_parameter("nested.threshold", 7)

    assert state.direct_parameter_paths("nested") == (
        DottedFieldPath("nested.threshold"),
        DottedFieldPath("nested.label"),
    )
    assert state.parameters["nested.threshold"] == 7


def test_resolved_snapshot_rejects_partial_parameter_state_without_recovery():
    state = ObjectState(ConfigWithNestedTopology(), scope_id="config")
    expected_topology = state.direct_parameter_paths("nested")
    state.parameters = None

    with pytest.raises(
        TypeError,
        match="parameters must remain a canonical flat dictionary",
    ):
        state._compute_resolved_snapshot()

    assert state.parameters is None
    assert state.direct_parameter_paths("nested") == expected_topology


def test_replacement_rebuilds_direct_parameter_topology_once(monkeypatch):
    state = ObjectState(PlainConfig(), scope_id="config")
    index_calls = 0
    original_index = state._index_parameter_paths

    def counted_index() -> None:
        nonlocal index_calls
        index_calls += 1
        original_index()

    monkeypatch.setattr(state, "_index_parameter_paths", counted_index)

    state.update_object_instance(ConfigWithNestedTopology())

    assert index_calls == 1
    assert state.direct_parameter_paths() == (
        DottedFieldPath("enabled"),
        DottedFieldPath("nested"),
    )
    assert state.direct_parameter_paths("nested") == (
        DottedFieldPath("nested.threshold"),
        DottedFieldPath("nested.label"),
    )


def test_update_object_instance_publishes_registry_resolved_change_without_local_subscriber():
    state = ObjectState(PlainConfig(), scope_id="config")
    events: list[tuple[str, set[str]]] = []

    def on_registry_change(scope_id: str, changed_paths: set[str]) -> None:
        events.append((scope_id, set(changed_paths)))

    ObjectStateRegistry.add_resolved_changed_callback(on_registry_change)

    try:
        state.update_object_instance(PlainConfig(threshold=2))
    finally:
        ObjectStateRegistry.remove_resolved_changed_callback(on_registry_change)

    assert events == [("config", {"threshold"})]


def test_dataclass_leaf_value_is_not_treated_as_flat_container():
    LazyConfigWithDataclassLeaf = LazyDataclassFactory.make_lazy_simple(
        ConfigWithDataclassLeaf
    )
    state = ObjectState(LazyConfigWithDataclassLeaf(), scope_id="config")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    value = DataclassLeaf("explicit")
    state.update_parameter("leaf", value)

    assert state.get_resolved_value("leaf") == value
    assert state.dirty_fields == {"leaf"}

    state.mark_saved()

    assert state.get_saved_resolved_value("leaf") == value
    assert state.dirty_fields == set()


def test_same_state_sibling_inheritance_invalidates_dataclass_leaf():
    @dataclass
    class ParentConfig:
        leaf: DataclassLeaf | None = None

    @dataclass
    class ChildConfig(ParentConfig):
        leaf: DataclassLeaf | None = None

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)
    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class RootConfig:
        parent_config: LazyParentConfig = field(default_factory=LazyParentConfig)
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    state = ObjectState(RootConfig(), scope_id="config")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    assert state.get_resolved_value("child_config.leaf") is None

    value = DataclassLeaf("inherited")
    state.update_parameter("parent_config.leaf", value)

    assert state.get_resolved_value("parent_config.leaf") == value
    assert state.get_resolved_value("child_config.leaf") == value


def test_raw_reconstruction_preserves_registered_lazy_runtime_identity():
    @dataclass
    class ViewerConfig(AnnotatedDataclassValidationMixin):
        port: Annotated[int, Gt(0)] = 5555

    lazy_viewer_config_type = LazyDataclassFactory.make_lazy_simple(ViewerConfig)

    @dataclass
    class RootConfig:
        viewer_config: ViewerConfig = field(default_factory=lazy_viewer_config_type)

    state = ObjectState(RootConfig(), scope_id="config")

    reconstructed = state.to_object()

    assert isinstance(reconstructed.viewer_config, lazy_viewer_config_type)
    assert object.__getattribute__(reconstructed.viewer_config, "port") is None


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
