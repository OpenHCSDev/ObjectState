from dataclasses import dataclass

import pytest

from objectstate import Inherit, LazyDataclassFactory, ObjectState, ObjectStateRegistry, Unset, set_base_config_type, set_global_config
from objectstate.field_value import Value
from objectstate.object_state import FieldProxy
from objectstate.inspection import (
    DIRTY_MARKER,
    SIGNATURE_DIFF_MARKER,
    FieldInspection,
    field_markers,
    state_markers,
)


@dataclass
class Inspected:
    count: int = 1
    label: str | None = "x"


@pytest.fixture(autouse=True)
def _registry():
    set_base_config_type(Inspected)
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


def test_markers_are_ordered_dirty_then_signature_difference():
    assert field_markers(dirty=True, signature_diff=True) == (DIRTY_MARKER, SIGNATURE_DIFF_MARKER)
    assert field_markers(dirty=False, signature_diff=True) == (SIGNATURE_DIFF_MARKER,)
    assert field_markers(dirty=False, signature_diff=False) == ()


def test_field_inspection_reports_value_edit_state_and_types():
    state = ObjectState(Inspected(count=3), scope_id="/inspected")
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    state.fields.label.write("y")
    label = state.fields.label.inspect()
    count = state.fields.count.inspect()
    assert (label.raw, label.resolved) == (Value("y"), Value("y"))
    assert label.resolved.available()
    assert label.dirty and label.last_changed and label.semantic_markers[0] == DIRTY_MARKER
    assert count.signature_diff and not count.dirty
    assert count.semantic_markers == (SIGNATURE_DIFF_MARKER,)
    assert (count.field_name, count.container_path, count.raw_value_type) == ("count", "", "int")
    assert count.declaring_type.endswith(".Inspected")
    assert not count.inherited_value and count.provenance is None
    assert state_markers(state) == (DIRTY_MARKER, SIGNATURE_DIFF_MARKER)


@pytest.mark.parametrize("raw, expected", [(None, Value(None)), (Unset(), Unset()), (Inherit(), Value("global")), ("", Value(""))])
def test_resolved_meaning_is_one_member_and_retains_literal_null(raw, expected):
    set_global_config(Inspected, Inspected(label="global"))
    lazy = LazyDataclassFactory.make_lazy_simple(Inspected)
    inspected = ObjectState(lazy(label=raw)).fields.label.inspect()
    from objectstate.field_value import FieldValue
    assert inspected.raw == FieldValue.of(raw)
    assert inspected.resolved == expected
    assert inspected.inherited_value == isinstance(raw, Inherit)


@pytest.mark.parametrize("directive", [Inherit(), Unset()])
def test_projection_sends_the_absent_member_to_the_view(directive):
    seen = []
    assert directive.project(lambda value: seen.append(value) or value) is directive
    assert seen == [directive]
    assert Value(None).project(lambda value: value) is None


def test_resolver_failure_propagates_its_original_identity():
    failure = RuntimeError("failed real field read")
    class FailedRead(FieldProxy):
        @property
        def resolved_member(self):
            raise failure
    state = ObjectState(Inspected())
    with pytest.raises(RuntimeError) as caught:
        FieldInspection.of(FailedRead(state, "label"))
    assert caught.value is failure
