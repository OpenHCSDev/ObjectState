from dataclasses import dataclass

import pytest

from objectstate import ObjectState, ObjectStateRegistry, set_base_config_type
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
    label: str = "x"


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
    state.update_parameter("label", "y")

    label = FieldInspection.of(state, "label")
    count = FieldInspection.of(state, "count")

    assert (label.raw_value, label.resolved_value, label.resolved_value_available) == ("y", "y", True)
    assert label.dirty and label.last_changed and label.semantic_markers[0] == DIRTY_MARKER
    assert count.signature_diff and not count.dirty
    assert count.semantic_markers == (SIGNATURE_DIFF_MARKER,)
    assert (count.field_name, count.container_path, count.raw_value_type) == ("count", "", "int")
    assert count.declaring_type.endswith(".Inspected")
    assert not count.inherited_value and count.provenance is None
    assert state_markers(state) == (DIRTY_MARKER, SIGNATURE_DIFF_MARKER)
