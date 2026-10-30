"""Native member edits retain distinct live, saved and historical topologies."""

from dataclasses import dataclass, field

import pytest

from objectstate import DottedFieldPath, ObjectState, ObjectStateRegistry


@dataclass(frozen=True)
class TextMember:
    text: str = 'original'


@dataclass(frozen=True)
class RangeMember:
    lower: int = 2
    upper: int = 8

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError('lower exceeds upper')


@dataclass(frozen=True)
class EmptyMember:
    pass


@dataclass
class MemberRoot:
    member: TextMember | RangeMember | EmptyMember | int | None = field(default_factory=TextMember)
    sibling: str = 'unchanged'
    excluded: str = 'retained'


@pytest.fixture(autouse=True)
def registry():
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


def assert_epoch(state: ObjectState, value, children: set[str]) -> None:
    expected = {'member', 'sibling'} | {f'member.{name}' for name in children}
    assert set(state.parameters) == expected
    assert set(state.parameter_structure.declarations) == expected
    assert set(state.parameter_structure.owner_paths) == expected
    assert set(state.parameter_structure.defaults) == expected
    assert set(state.parameter_structure.descriptions) == expected
    assert {path.value for path in state.direct_parameter_paths('member')} == {
        f'member.{name}' for name in children
    }
    assert state.get_resolved_value('member') == value
    assert type(state.get_resolved_value('member')) is type(value)
    assert state.to_object().member == value
    assert state.to_resolved_object().member == value
    assert state.to_object().excluded == 'retained'
    assert state.get_resolved_value('sibling') == 'unchanged'
    assert state.parameter_structure.exclusions == ['excluded']


def test_unrelated_members_replace_all_live_metadata_but_not_saved_epoch():
    state = ObjectState(MemberRoot(), scope_id='members', exclude_params=['excluded'])
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    events: list[set[str]] = []
    state.on_resolved_changed(lambda paths: events.append(set(paths)))

    changed = state.update_parameter('member', RangeMember())
    assert changed == {'member.text', 'member.lower', 'member.upper'}
    assert events == [changed]
    assert_epoch(state, RangeMember(), {'lower', 'upper'})
    saved_structure = state._saved_structure
    saved_values = state._saved_resolved
    for _ in range(3):
        assert state.get_saved_resolved_value('member') == TextMember()
        assert state.to_saved_resolved_object().member == TextMember()
        assert state._saved_structure is saved_structure
        assert state._saved_resolved is saved_values
    assert state.is_raw_dirty
    assert state.dirty_fields == {'member.text', 'member.lower', 'member.upper'}

    state.update_parameter('member.lower', 3)
    assert_epoch(state, RangeMember(lower=3), {'lower', 'upper'})
    assert state.to_saved_resolved_object().member == TextMember()
    state.mark_saved()
    assert state.get_saved_resolved_value('member') == RangeMember(lower=3)
    assert state.to_saved_resolved_object().member == RangeMember(lower=3)
    assert not state.is_raw_dirty
    assert not state.dirty_fields
    assert state._saved_structure is not saved_structure
    assert set(state._saved_structure.declarations) == set(state.parameters)


@pytest.mark.parametrize('value,children,container', [
    (RangeMember(), {'lower', 'upper'}, True),
    (EmptyMember(), set(), True),
    (None, set(), False),
    (17, set(), False),
    (TextMember('return'), {'text'}, True),
])
def test_member_shape_round_trip_from_different_prior_shapes(value, children, container):
    state = ObjectState(MemberRoot(), exclude_params=['excluded'])
    state.update_parameter('member', RangeMember())
    state.update_parameter('member', None)
    state.update_parameter('member', value)
    assert_epoch(state, value, children)
    assert state.parameter_structure.is_container_parameter('member') == container
    assert state.to_saved_resolved_object().member == TextMember()
    assert state.get_saved_resolved_value('member.text') == 'original'
    assert state.is_raw_dirty
    state.mark_saved()
    assert state.get_saved_resolved_value('member') == value
    assert type(state.get_saved_resolved_value('member')) is type(value)
    assert state.to_saved_resolved_object().member == value
    assert not state.is_raw_dirty
    assert not state.dirty_fields


def test_failed_native_ancestor_preparation_changes_nothing():
    state = ObjectState(MemberRoot(RangeMember()), scope_id='members', exclude_params=['excluded'])
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    ObjectStateRegistry.record_snapshot('before refusal')
    parameters = dict(state.parameters)
    saved = dict(state._saved_parameters)
    structure = state.parameter_structure
    history = [entry.id for entry in ObjectStateRegistry.get_branch_history()]
    token = ObjectStateRegistry._token
    events = []
    state.on_resolved_changed(lambda paths: events.append(paths))
    with pytest.raises(ValueError, match='lower exceeds upper'):
        state.update_parameter('member.lower', 99)
    assert state.parameters == parameters
    assert state._saved_parameters == saved
    assert state.parameter_structure is structure
    assert ObjectStateRegistry._token == token
    assert [entry.id for entry in ObjectStateRegistry.get_branch_history()] == history
    assert events == []
    assert_epoch(state, RangeMember(), {'lower', 'upper'})


def test_registry_undo_redo_restores_native_members_and_their_own_baselines():
    state = ObjectState(MemberRoot(), scope_id='members', exclude_params=['excluded'])
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    ObjectStateRegistry.record_snapshot('original')
    state.update_parameter('member', RangeMember())
    state.update_parameter('member.lower', 3)
    assert ObjectStateRegistry.time_travel_back()
    assert_epoch(state, RangeMember(), {'lower', 'upper'})
    assert state.to_saved_resolved_object().member == TextMember()
    assert ObjectStateRegistry.time_travel_back()
    assert_epoch(state, TextMember(), {'text'})
    assert not state.is_raw_dirty
    assert ObjectStateRegistry.time_travel_forward()
    assert_epoch(state, RangeMember(), {'lower', 'upper'})
    assert state.to_saved_resolved_object().member == TextMember()
    assert state.is_raw_dirty
    assert ObjectStateRegistry.time_travel_forward()
    assert_epoch(state, RangeMember(lower=3), {'lower', 'upper'})
    assert state.parameter_structure.path('member.lower') == DottedFieldPath('member.lower')
    assert state.get_saved_resolved_value('member.text') == 'original'
