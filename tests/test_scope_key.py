import pickle

import pytest

from objectstate import ObjectStateRegistry, ScopeKey


def test_scope_key_owns_the_hierarchy_grammar():
    step = ScopeKey.of("/plate1", "step_0")
    function = step.child("func_1")

    assert function == "/plate1::step_0::func_1"
    assert function.parts == ("/plate1", "step_0", "func_1")
    assert (function.depth, function.last) == (3, "func_1")
    assert function.root == "/plate1" and function.parent == step
    assert function.ancestors() == ("", "/plate1", step, function)
    assert ScopeKey(None) == ScopeKey("") and ScopeKey().is_global
    assert ScopeKey().parts == () and ScopeKey().ancestors() == ("",)


def test_containment_is_by_whole_segments():
    plate = ScopeKey("/plate1")

    assert plate.contains("/plate1") and plate.contains("/plate1::step_0")
    assert not plate.contains("/plate10")
    assert not plate.contains("/plate10::step_0")
    assert not plate.strictly_contains("/plate1")
    assert ScopeKey().contains("/anything") and ScopeKey().strictly_contains("/anything")
    assert not ScopeKey("/plate1::step_0").contains("/plate1")


@pytest.mark.parametrize("segment", ("", "a::b"))
def test_a_segment_is_one_nonempty_segment(segment):
    with pytest.raises(ValueError):
        ScopeKey("/plate").child(segment)


def test_scope_key_is_its_text_as_a_key_and_when_pickled():
    key = ScopeKey.of("/plate", "step")

    assert {"/plate::step": 1}[key] == 1
    restored = pickle.loads(pickle.dumps(key))
    assert type(restored) is ScopeKey and restored == key


def test_registry_keys_are_scope_keys():
    assert type(ObjectStateRegistry._normalize_scope_id(None)) is ScopeKey
