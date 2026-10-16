"""Lazy dataclasses written as Python source keep their raw values."""

from dataclasses import dataclass, field
from enum import Enum

import pytest
from pycodify import Assignment, FormatContext, generate_python_source

from objectstate import LazyDataclassFactory
from objectstate.codegen import field_needs_source
from objectstate.field_access import DataclassFieldAccess
from objectstate.lazy_factory import LazyResolutionDataclass


class Speed:
    class Mode(Enum):
        FAST = "fast"
        SLOW = "slow"


@dataclass
class Inner:
    depth: int = 1
    mode: Speed.Mode = Speed.Mode.FAST


@dataclass
class Outer:
    name: str = "a"
    inner: Inner = field(default_factory=Inner)


LazyInner = LazyDataclassFactory.make_lazy_simple(Inner)
LazyOuter = LazyDataclassFactory.make_lazy_simple(Outer)


def _load(value, clean_mode):
    source = generate_python_source(Assignment("value", value), clean_mode=clean_mode)
    namespace = {}
    exec(source, namespace)
    return source, namespace["value"]


def _raw(value):
    return {
        name: _raw(raw) if isinstance(raw, LazyInner) else raw
        for name in ("name", "inner", "depth", "mode")
        if DataclassFieldAccess.has_field(value, name)
        for raw in (DataclassFieldAccess.raw_value(value, name),)
    }


VALUES = (
    LazyOuter(),
    LazyOuter(name="b"),
    LazyOuter(inner=LazyInner()),
    LazyOuter(inner=LazyInner(depth=3, mode=Speed.Mode.SLOW)),
    LazyOuter(name=None, inner=LazyInner(depth=None)),
)


@pytest.mark.parametrize("clean_mode", (True, False))
@pytest.mark.parametrize("value", VALUES, ids=repr)
def test_source_loads_back_with_equal_raw_values(value, clean_mode):
    _, loaded = _load(value, clean_mode)
    assert type(loaded) is type(value)
    assert _raw(loaded) == _raw(value)


def test_clean_source_preserves_literal_null_and_explicit_empty_nested_configs():
    source, loaded = _load(LazyOuter(name="b", inner=LazyInner(depth=None)), clean_mode=True)
    assert "name='b'" in source
    assert "depth=None" in source
    assert DataclassFieldAccess.raw_value(DataclassFieldAccess.raw_value(loaded, "inner"), "depth") is None

    source, _ = _load(LazyOuter(name="b", inner=LazyInner()), clean_mode=True)
    assert "inner=LazyInner()" in source
    assert "depth" not in source

    source, _ = _load(LazyOuter(name="b"), clean_mode=True)
    assert "inner" not in source


def test_full_source_writes_every_raw_field():
    source, _ = _load(LazyInner(mode=Speed.Mode.SLOW), clean_mode=False)
    assert "depth=Inherit()" in source
    assert "mode=Speed.Mode.SLOW" in source


def test_field_needs_source_compares_lazy_raw_values():
    clean = FormatContext(clean_mode=True)
    assert not field_needs_source(LazyInner(), LazyInner(), clean)
    assert not field_needs_source(LazyInner(depth=2), LazyInner(depth=2), clean)
    assert field_needs_source(LazyInner(depth=2), LazyInner(), clean)
    assert field_needs_source(3, 1, clean)
    assert not field_needs_source(1, 1, clean)
    assert field_needs_source(LazyInner(), LazyInner(), FormatContext())


@dataclass
class Inheriting(LazyResolutionDataclass):
    """A custom accessor transforms null; source still owns the stored datum."""

    mode: str | None = None
    size: int = 4

    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        return "resolved" if name == "mode" and value is None else value


@pytest.mark.parametrize("clean_mode", (True, False))
def test_inheriting_base_config_keeps_its_raw_none(clean_mode):
    source, loaded = _load(Inheriting(size=5), clean_mode)
    assert "resolved" not in source
    assert DataclassFieldAccess.raw_value(loaded, "mode") is None
    assert DataclassFieldAccess.raw_value(loaded, "size") == 5
