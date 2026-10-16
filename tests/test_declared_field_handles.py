"""Declared identities and field meaning through real editing lifetimes."""
from dataclasses import dataclass, field as dataclass_field

import pytest

from objectstate import (
    DataclassFieldAccess, Inherit, LazyDataclassFactory, ObjectState, Unset,
    set_base_config_type, set_global_config,
)
from objectstate.field_access import FieldAccessError


@dataclass
class Detail:
    value: int | None = 8


@dataclass
class Settings:
    text: str | None = None
    count: int | None = 4
    detail: Detail | None = dataclass_field(default_factory=Detail)


def editor():
    set_base_config_type(Settings)
    set_global_config(Settings, Settings(count=77, detail=Detail(91)))
    lazy_detail = LazyDataclassFactory.make_lazy_simple(Detail)
    lazy_settings = LazyDataclassFactory.make_lazy_simple(Settings)
    return ObjectState(lazy_settings(text=None, detail=lazy_detail())), lazy_settings, lazy_detail


@pytest.mark.parametrize('stored, expected', [(None, None), (Inherit(), 77), (Unset(), Unset()), (0, 0)])
def test_field_meaning_in_full_and_targeted_projections(stored, expected):
    state, _, _ = editor()
    count = state.field(Settings, 'count')
    count.write(stored)
    assert count.raw == stored
    assert count.value == expected
    assert DataclassFieldAccess.raw_value(state.to_object(), 'count') == stored
    assert state.to_resolved_object().count == expected


def test_subscription_identity_and_release():
    state, _, _ = editor()
    text = state.fields.text
    changes = []
    roots = []
    release = text.subscribe(lambda changed: changes.append((text.value, changed)))
    release_root = state.fields.subscribe(roots.append)
    text.write('edited')
    assert text.dirty
    text.reset()
    assert text.value is None and not text.dirty
    assert [value for value, _ in changes] == ['edited', None]
    assert all(changed == {text} for _, changed in changes)
    assert roots and all(text in changed for changed in roots)
    release()
    release_root()
    text.write('released')
    assert len(changes) == 2
    assert text.inspect().declaring_type.endswith('.Settings')


def test_identity_survives_restore_and_same_declaration_replacement():
    state, lazy_settings, lazy_detail = editor()
    text = state.fields.text
    identity_hash = hash(text)
    text.write('edited')
    state.restore_saved()
    assert text.value is None
    assert text == state.fields.text and hash(text) == identity_hash
    state.update_object_instance(lazy_settings(text='replacement', detail=lazy_detail(value=12)))
    assert text.value == 'replacement'
    assert text == state.fields.text and hash(text) == identity_hash


def test_container_presence_dominates_retained_child_drafts():
    state, _, _ = editor()
    detail = state.field(Settings, 'detail')
    child = state.fields.bind(Settings, ('detail', 'value'))
    assert detail.declaring_type is Settings
    assert child.declaring_type is Detail
    assert detail.value.value == detail.saved_value.value == 91
    child.write(15)
    detail.write(None)
    assert child.raw == 15
    assert detail.value is None and isinstance(child.value, Unset)
    assert state.to_resolved_object().detail is None
    assert detail.saved_value.value == 91
    detail.write(Inherit())
    assert detail.value.value == child.value == 91
    assert state.to_resolved_object().detail.value == 91
    detail.write(Unset())
    assert isinstance(detail.value, Unset) and isinstance(child.value, Unset)
    detail.write(Detail(12))
    assert detail.value.value == child.value == 12


def test_regular_declaration_explicitly_requests_inheritance():
    state, _, _ = editor()
    state.update_object_instance(Settings(count=Inherit()))
    assert state.fields.count.value == 77
    state.fields.count.write(None)
    assert state.fields.count.value is None


def test_wrong_and_retired_declarations_fail_at_the_handle():
    state, _, _ = editor()
    with pytest.raises(FieldAccessError):
        state.field(Settings, 'typo')
    text = state.fields.text
    @dataclass
    class Other:
        text: str = 'unrelated'
    state.update_object_instance(Other())
    assert not text.present
    with pytest.raises(FieldAccessError):
        text.write('wrong target')
    assert state.fields.text.value == 'unrelated'
    for deleted in ('parameters', 'get_resolved_value', 'get_saved_resolved_value', 'update_parameter', 'reset_parameter', 'on_state_changed', 'on_resolved_changed', 'type_for_path', 'get_provenance'):
        assert not hasattr(state, deleted)
