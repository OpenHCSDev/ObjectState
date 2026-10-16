from abc import ABC, abstractmethod
from dataclasses import dataclass

import pytest

from objectstate import DataclassFieldAccess, DottedFieldPath, FieldAccessError


@dataclass
class NestedConfig:
    value: int = 7


@dataclass
class RegularConfig:
    child: NestedConfig
    name: str = "regular"


@dataclass(slots=True)
class SlottedConfig:
    child: NestedConfig
    name: str = "slotted"


class AbstractFieldConfig(ABC):
    @property
    @abstractmethod
    def value(self) -> int:
        """Field exposed by concrete slotted dataclasses."""


@dataclass(frozen=True, slots=True)
class SlottedAbstractConfig(AbstractFieldConfig):
    value: int = 11


@pytest.mark.parametrize(
    ("value", "parent", "lineage", "field_name"),
    [
        ("", "", (), ""),
        ("name", "", ("name",), "name"),
        ("child.value", "child", ("child.value", "child"), "value"),
        ("outer.child.value", "outer.child", ("outer.child.value", "outer.child", "outer"), "value"),
    ],
)
def test_dotted_path_owns_parent_lineage_and_leaf_name(value, parent, lineage, field_name) -> None:
    path = DottedFieldPath(value)

    assert path.field_name == field_name
    assert path.parent == DottedFieldPath(parent)
    assert tuple(step.value for step in path.lineage) == lineage
    assert path.parent.child(path.field_name) == path


@pytest.mark.parametrize(
    ("owner", "candidate", "child"),
    [
        ("", "", None),
        ("", "value", "value"),
        ("", "source_bindings.source_filters[0].match_type", "source_bindings"),
        ("processing_config", "processing_config.variable_components[1]", "variable_components"),
        ("processing_config", "processing_config", None),
        ("processing_config", "processing_config[0].value", None),
        ("processing_config", "unrelated.value", None),
        ("processing_config", "processing_config_extra.value", None),
    ],
)
def test_dotted_path_owns_direct_child_selection(owner, candidate, child) -> None:
    path = DottedFieldPath(owner)
    assert path.direct_child_name(candidate) == child
    assert path.direct_child_name(DottedFieldPath(candidate)) == child


def test_raw_value_reads_regular_dataclass_field() -> None:
    config = RegularConfig(child=NestedConfig())

    assert DataclassFieldAccess.raw_value(config, "name") == "regular"


def test_raw_value_reads_slotted_dataclass_field() -> None:
    config = SlottedConfig(child=NestedConfig())

    assert DataclassFieldAccess.raw_value(config, "name") == "slotted"


def test_raw_value_reads_slotted_field_when_abc_adds_instance_dict() -> None:
    config = SlottedAbstractConfig()

    assert DataclassFieldAccess.raw_value(config, "value") == 11


def test_raw_path_traverses_dotted_field_path() -> None:
    config = SlottedConfig(child=NestedConfig(value=42))

    assert DataclassFieldAccess.raw_path(config, DottedFieldPath("child.value")) == 42


def test_raw_value_rejects_missing_dataclass_field() -> None:
    config = RegularConfig(child=NestedConfig())

    with pytest.raises(FieldAccessError):
        DataclassFieldAccess.raw_value(config, "missing")
