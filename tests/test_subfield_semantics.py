"""ObjectState structural subfield semantic projection tests."""

from dataclasses import dataclass, field

import pytest

from objectstate import (
    DottedFieldPath,
    MISSING,
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    StructuralFieldPath,
    StructuralValuePath,
    replace_raw,
)


@pytest.fixture(autouse=True)
def clear_objectstate_registry() -> None:
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


@dataclass(frozen=True, slots=True)
class Clause:
    subject: str
    match_type: str
    value: str | None


@dataclass(frozen=True, slots=True)
class Holder:
    clauses: tuple[Clause, ...] | None = None


@dataclass(frozen=True, slots=True)
class EnableableHolder:
    enabled: bool | None = None
    clauses: tuple[Clause, ...] | None = None


def _path(row_index: int, field_name: str) -> StructuralValuePath:
    return StructuralValuePath().child_index(row_index).child_field(field_name)


def test_structural_field_path_parses_owner_and_relative_suffix() -> None:
    structural_path = StructuralFieldPath.from_display_path(
        "source_bindings_config.source_filters[0].match_type"
    )

    assert structural_path is not None
    assert structural_path.owner_field_path == DottedFieldPath(
        "source_bindings_config.source_filters"
    )
    assert structural_path.relative_path == _path(0, "match_type")


def test_tuple_dataclass_leaf_semantics_detect_only_changed_leaf() -> None:
    state = ObjectState(
        Holder(clauses=(Clause("file", "contains", "DAPI"),)),
        scope_id="subfield",
    )
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    state.update_parameter(
        "clauses",
        (Clause("file", "contains", "GFP"),),
    )

    index = state.subfield_semantics(DottedFieldPath("clauses"))
    subject = index.leaf_for(_path(0, "subject"))
    match_type = index.leaf_for(_path(0, "match_type"))
    value = index.leaf_for(_path(0, "value"))

    assert subject is not None
    assert match_type is not None
    assert value is not None
    assert subject.dirty is False
    assert match_type.dirty is False
    assert value.dirty is True
    assert value.raw_value == "GFP"
    assert value.saved_resolved_value == "DAPI"
    assert value.semantic_markers == ("*", "_")


def test_container_replacement_reports_child_semantic_change_only() -> None:
    @dataclass
    class RootConfig:
        bindings: EnableableHolder = field(
            default_factory=lambda: EnableableHolder(
                enabled=True,
                clauses=(Clause("file", "contains", "DAPI"),),
            )
        )

    state = ObjectState(RootConfig(), scope_id="subfield")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    resolved_events: list[set[str]] = []
    state_events: list[set[str]] = []
    state.on_resolved_changed(lambda paths: resolved_events.append(set(paths)))
    state.on_state_changed(lambda paths: state_events.append(set(paths)))

    changed_paths = state.update_parameter(
        "bindings",
        replace_raw(state.parameters["bindings"], enabled=None),
    )

    assert "bindings.enabled" in state._last_changed_concrete_paths
    assert "bindings" not in state._last_changed_concrete_paths
    assert "bindings.enabled" in changed_paths
    assert "bindings" not in changed_paths
    assert resolved_events
    assert state_events
    assert all(event == {"bindings.enabled"} for event in resolved_events)
    assert all(event == {"bindings.enabled"} for event in state_events)


def test_missing_default_leaf_marks_signature_diff_without_confusing_none() -> None:
    state = ObjectState(Holder(), scope_id="subfield")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    state.update_parameter(
        "clauses",
        (Clause("file", "is_image", None),),
    )

    leaf = state.subfield_semantics(DottedFieldPath("clauses")).leaf_for(
        _path(0, "value")
    )

    assert leaf is not None
    assert leaf.raw_present is True
    assert leaf.raw_value is None
    assert leaf.signature_default_present is False
    assert leaf.signature_default_value is MISSING
    assert leaf.signature_diff is True


def test_inherited_tuple_cells_are_marked_inherited() -> None:
    @dataclass
    class ParentConfig:
        clauses: tuple[Clause, ...] | None = None

    @dataclass
    class ChildConfig(ParentConfig):
        clauses: tuple[Clause, ...] | None = None

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)
    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class RootConfig:
        parent_config: LazyParentConfig = field(default_factory=LazyParentConfig)
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    state = ObjectState(RootConfig(), scope_id="subfield")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    state.update_parameter(
        "parent_config.clauses",
        (Clause("file", "contains", "DAPI"),),
    )
    state.mark_saved()

    assert state.get_resolved_value("child_config.clauses") == (
        Clause("file", "contains", "DAPI"),
    )
    index = state.subfield_semantics(DottedFieldPath("child_config.clauses"))
    leaf = index.leaf_for(_path(0, "value"))

    assert leaf is not None
    assert leaf.raw_present is False
    assert leaf.raw_value is MISSING
    assert leaf.resolved_value == "DAPI"
    assert leaf.saved_resolved_value == "DAPI"
    assert leaf.dirty is False
    assert leaf.signature_diff is False
    assert leaf.inherited_value is True
    assert index.owner_inherited_value is True


def test_inherited_tuple_recompute_notifies_structural_leaf_paths() -> None:
    @dataclass
    class ParentConfig:
        clauses: tuple[Clause, ...] | None = None

    @dataclass
    class ChildConfig(ParentConfig):
        clauses: tuple[Clause, ...] | None = None

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)
    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class RootConfig:
        parent_config: LazyParentConfig = field(default_factory=LazyParentConfig)
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    state = ObjectState(RootConfig(), scope_id="subfield")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    state.update_parameter(
        "parent_config.clauses",
        (Clause("file", "contains", "DAPI"),),
    )
    assert state.get_resolved_value("child_config.clauses") == (
        Clause("file", "contains", "DAPI"),
    )

    changed_notifications: list[set[str]] = []
    state.on_resolved_changed(
        lambda changed_paths: changed_notifications.append(set(changed_paths))
    )
    state.update_parameter(
        "parent_config.clauses",
        (Clause("file", "contains", "GFP"),),
    )
    assert state.get_resolved_value("child_config.clauses") == (
        Clause("file", "contains", "GFP"),
    )

    changed = set().union(*changed_notifications)
    assert "parent_config.clauses[0].value" in changed
    assert "child_config.clauses[0].value" in changed
    concrete_parent_change = state.last_changed_field
    assert concrete_parent_change is not None
    assert concrete_parent_change.startswith("parent_config.clauses[0].")
    assert not concrete_parent_change.startswith("child_config.")


def test_time_travel_navigation_field_ignores_inherited_resolved_fanout() -> None:
    @dataclass
    class ParentConfig:
        clauses: tuple[Clause, ...] | None = None

    @dataclass
    class ChildConfig(ParentConfig):
        clauses: tuple[Clause, ...] | None = None

    LazyParentConfig = LazyDataclassFactory.make_lazy_simple(ParentConfig)
    LazyChildConfig = LazyDataclassFactory.make_lazy_simple(ChildConfig)

    @dataclass
    class RootConfig:
        parent_config: LazyParentConfig = field(default_factory=LazyParentConfig)
        child_config: LazyChildConfig = field(default_factory=LazyChildConfig)

    state = ObjectState(RootConfig(), scope_id="subfield")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    state.update_parameter(
        "parent_config.clauses",
        (Clause("file", "contains", "DAPI"),),
    )

    assert state.get_resolved_value("child_config.clauses") == (
        Clause("file", "contains", "DAPI"),
    )
    concrete_parent_change = state.last_changed_field
    assert concrete_parent_change is not None
    assert concrete_parent_change.startswith("parent_config.clauses[0].")
    assert not concrete_parent_change.startswith("child_config.")

    changed_notifications: list[set[str]] = []
    state.on_resolved_changed(
        lambda changed_paths: changed_notifications.append(set(changed_paths))
    )

    assert ObjectStateRegistry.time_travel_back()

    changed = set().union(*changed_notifications)
    assert "child_config.clauses[0].value" in changed
    assert state.last_changed_field == concrete_parent_change

    assert ObjectStateRegistry.time_travel_forward()
    assert state.last_changed_field == concrete_parent_change
