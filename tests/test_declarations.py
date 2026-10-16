"""Declaration-owned behavior, meaning and collection traversal."""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from objectstate import DottedFieldPath, ObjectState
from objectstate.declarations import FactoryDefault, InheritedDefault, ValueDeclaration, ValueDefault
from objectstate.field_value import ConfigValue, Inherit, Unset, Value
from objectstate.subfield_semantics import StructuralValuePath


@dataclass
class Item:
    text: str | None = "default"


@dataclass
class Rows:
    items: tuple[Item, ...] | None = None


def test_payload_does_not_choose_a_field_kind():
    payload = Item()
    member = ValueDeclaration.of(object).admit(payload)
    assert type(member) is Value
    assert member.stored is payload
    assert not hasattr(member, "read_raw")
    assert not hasattr(member, "declared_fields")
    assert isinstance(ValueDeclaration.of(Item).admit(payload), ConfigValue)


def test_nullable_scope_preserves_null_and_directives():
    declaration = ValueDeclaration.of(Item | None)
    assert declaration.admit(None).stored is None
    assert declaration.admit(None).available()
    assert not declaration.scope_available(declaration.admit(None))
    assert declaration.admit(Inherit()) == Inherit()
    assert declaration.admit(Unset()) == Unset()
    assert declaration.scope_available(declaration.admit(Item()))


@pytest.mark.parametrize("annotation, value, expected", [
    (tuple[int, ...], [1, 2], (1, 2)),
    (list[int], (1, 2), [1, 2]),
    (tuple[int, str], [1, "two"], (1, "two")),
    (tuple[int, ...] | None, [1], (1,)),
    (tuple[int, ...] | None, None, None),
])
def test_declared_collection_shape_owns_normalization(annotation, value, expected):
    assert ValueDeclaration.of(annotation).normalize_data(value) == expected


def test_scalar_declaration_does_not_classify_a_sequence_payload():
    payload = [1, 2]
    assert ValueDeclaration.of(object).normalize_data(payload) is payload


def test_collection_serialization_uses_element_declarations():
    declaration = ValueDeclaration.of(tuple[Item, ...])
    member = declaration.admit((Item(Inherit()), Item(None), Item("")))
    assert member.for_serialization(lambda owner, name: SimpleNamespace(value="inherited")) == (
        Item("inherited"), Item(None), Item("")
    )


def test_collection_leaves_use_the_bound_declaration():
    state = ObjectState(Rows((Item("before"),)))
    state.fields.items.write((Item("after"),))
    index = state.subfield_semantics(DottedFieldPath("items"))
    leaf = index.leaf_for(StructuralValuePath().child_index(0).child_field("text"))
    assert leaf.raw_value == "after"
    assert leaf.saved_resolved_value == "before"
    assert leaf.dirty
    assert leaf.signature_default_value == Unset()


def test_inherited_defaults_have_one_typed_metadata_owner():
    literal = ValueDefault(None)
    factory = FactoryDefault(lambda: 7)
    assert isinstance(literal, InheritedDefault)
    assert literal.value() is None
    assert factory.value() == 7
    declaration = ValueDeclaration.of(Item)
    with pytest.raises(KeyError):
        declaration.own_default("not_declared")
    with pytest.raises(KeyError):
        declaration.inherited_default("not_declared")
