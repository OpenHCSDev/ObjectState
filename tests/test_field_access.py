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
