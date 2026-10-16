"""Meaning stays nominal through the existing declaration-aware JSON codec."""
import json
from dataclasses import dataclass

import pytest
from python_introspect import dataclass_from_mapping, to_jsonable

from objectstate.field_access import DataclassFieldAccess
from objectstate.field_value import FieldValue, Inherit, Unset, Value
from objectstate.parameter_structure import ParameterStructure


@dataclass
class Meanings:
    raw: FieldValue
    resolved: FieldValue


@pytest.mark.parametrize("member, stored", [
    (Value(None), {"Value": {"value": None}}),
    (Value(False), {"Value": {"value": False}}),
    (Value(0), {"Value": {"value": 0}}),
    (Value(""), {"Value": {"value": ""}}),
    (Value("None"), {"Value": {"value": "None"}}),
    (Value("Unset()"), {"Value": {"value": "Unset()"}}),
    (Inherit(), {"Inherit": {}}),
    (Unset(), {"Unset": {}}),
])
def test_member_tags_preserve_null_directives_and_literal_data(member, stored):
    original = Meanings(member, member)
    wire = json.loads(json.dumps(to_jsonable(original)))
    assert wire == {"raw": stored, "resolved": stored}
    decoded = dataclass_from_mapping(Meanings, wire)
    assert decoded == original
    assert type(decoded.raw) is type(member)
    assert type(decoded.resolved) is type(member)


@pytest.mark.parametrize("wire", [None, {}, {"Unknown": {}}, {"Value": {}}, {"Inherit": {"value": None}}])
def test_missing_or_untyped_members_do_not_become_literal_null(wire):
    with pytest.raises((TypeError, ValueError)):
        dataclass_from_mapping(Meanings, {"raw": wire, "resolved": {"Unset": {}}})


@dataclass
class EmptyConfig:
    pass


@pytest.mark.parametrize("member", [Inherit(), Unset(), Value(None)])
def test_meaning_dataclasses_are_not_configuration_containers(member):
    assert not DataclassFieldAccess.is_container(member)
    assert not DataclassFieldAccess.is_config_type(type(member))
    assert DataclassFieldAccess.is_container(EmptyConfig())
    assert DataclassFieldAccess.is_config_type(EmptyConfig)
    structure = ParameterStructure()
    values = {"child": member, "child.retained_draft": 99, "actual": EmptyConfig()}
    assert structure.reconstruct("child", values, EmptyConfig()) is member
    assert list(structure.container_types(values)) == [("actual", EmptyConfig)]
