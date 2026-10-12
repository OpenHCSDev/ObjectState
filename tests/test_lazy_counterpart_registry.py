"""The base/lazy relation is owned by one registry, not by a class-name convention."""

from dataclasses import dataclass

import pytest

from objectstate import LazyDataclassFactory, abbreviation, get_base_type_for_lazy, lazy_factory
from objectstate.lazy_factory import (
    create_global_default_decorator,
    get_group_abbreviation,
    get_lazy_type_for_base,
    register_lazy_type_mapping,
)


@pytest.fixture
def global_default():
    """A global-default decorator whose pending injections are dropped afterwards."""

    @dataclass(frozen=True)
    class GlobalCounterpartConfig:
        pass

    yield create_global_default_decorator(GlobalCounterpartConfig)
    del lazy_factory._pending_injections[GlobalCounterpartConfig.__name__]


def _abbreviation_first(global_default, name):
    @global_default
    @abbreviation(name)
    @dataclass(frozen=True)
    class WellFilterConfig:
        well: str = "A01"

    return WellFilterConfig


def _abbreviation_last(global_default, name):
    @abbreviation(name)
    @global_default
    @dataclass(frozen=True)
    class WellFilterConfig:
        well: str = "A01"

    return WellFilterConfig


DECORATOR_ORDERS = pytest.mark.parametrize(
    "define", [_abbreviation_first, _abbreviation_last]
)


@DECORATOR_ORDERS
def test_class_inside_function_gets_abbreviation_on_base_and_lazy(define, global_default):
    config = define(global_default, "wfc")
    lazy = get_lazy_type_for_base(config)

    assert get_base_type_for_lazy(lazy) is config
    assert get_group_abbreviation(config) == "wfc"
    assert get_group_abbreviation(lazy) == "wfc"


@DECORATOR_ORDERS
def test_same_named_classes_in_one_module_keep_their_own_abbreviation(
    define, global_default
):
    first = define(global_default, "first")
    second = define(global_default, "second")

    assert first.__name__ == second.__name__
    assert first.__module__ == second.__module__
    first_lazy = get_lazy_type_for_base(first)
    second_lazy = get_lazy_type_for_base(second)
    assert first_lazy is not second_lazy
    assert [get_group_abbreviation(t) for t in (first, first_lazy)] == ["first"] * 2
    assert [get_group_abbreviation(t) for t in (second, second_lazy)] == ["second"] * 2


@DECORATOR_ORDERS
def test_renamed_prefix_does_not_break_the_relation(define, global_default, monkeypatch):
    monkeypatch.setattr(lazy_factory, "LAZY_CLASS_NAME_PREFIX", "Deferred")
    config = define(global_default, "wfc")
    lazy = get_lazy_type_for_base(config)

    assert lazy.__name__ == "DeferredWellFilterConfig"
    assert get_group_abbreviation(lazy) == "wfc"

    monkeypatch.setattr(lazy_factory, "LAZY_CLASS_NAME_PREFIX", "Lazy")
    assert LazyDataclassFactory.make_lazy_simple(config) is lazy
    assert get_group_abbreviation(lazy) == "wfc"


def test_explicit_abbreviation_parameter_reaches_the_lazy_class(global_default):
    @global_default(abbreviation="pp")
    @dataclass(frozen=True)
    class PathPlanningConfig:
        suffix: str = "_out"

    assert get_group_abbreviation(PathPlanningConfig) == "pp"
    assert get_group_abbreviation(get_lazy_type_for_base(PathPlanningConfig)) == "pp"


def test_two_different_abbreviations_for_one_class_raise(global_default):
    with pytest.raises(ValueError, match="already declares abbreviation 'pp'"):

        @abbreviation("other")
        @global_default(abbreviation="pp")
        @dataclass(frozen=True)
        class PathPlanningConfig:
            suffix: str = "_out"


def test_subclass_without_declaration_reads_its_ancestor(global_default):
    parent = _abbreviation_first(global_default, "wfc")

    @global_default
    @dataclass(frozen=True)
    class StepWellFilterConfig(parent):
        pass

    @abbreviation("own")
    @global_default
    @dataclass(frozen=True)
    class NamedWellFilterConfig(parent):
        pass

    @global_default
    @abbreviation("below")
    @dataclass(frozen=True)
    class RebuiltWellFilterConfig(parent):
        pass

    assert get_group_abbreviation(get_lazy_type_for_base(RebuiltWellFilterConfig)) == "below"
    assert get_group_abbreviation(get_lazy_type_for_base(StepWellFilterConfig)) == "wfc"
    assert get_group_abbreviation(get_lazy_type_for_base(NamedWellFilterConfig)) == "own"
    assert get_group_abbreviation(parent) == "wfc"


def test_registry_refuses_a_second_counterpart_in_either_direction():
    @dataclass(frozen=True)
    class First:
        value: int = 0

    @dataclass(frozen=True)
    class Second:
        value: int = 0

    @dataclass(frozen=True)
    class Unregistered:
        value: int = 0

    lazy_first = LazyDataclassFactory.make_lazy_simple(First)
    lazy_second = LazyDataclassFactory.make_lazy_simple(Second)

    with pytest.raises(ValueError, match="already registered"):
        register_lazy_type_mapping(lazy_first, Second)
    with pytest.raises(ValueError, match="already owns lazy type"):
        register_lazy_type_mapping(Unregistered, First)
    with pytest.raises(ValueError, match="already owns lazy type"):
        LazyDataclassFactory.make_lazy_simple(First, "OtherLazyFirst")
    assert get_lazy_type_for_base(First) is lazy_first
    assert get_base_type_for_lazy(lazy_second) is Second
    assert get_base_type_for_lazy(Unregistered) is None


def test_no_lazy_class_is_looked_up_by_constructed_name():
    import inspect

    source = inspect.getsource(lazy_factory)
    assert "LAZY_CONFIG_PREFIX" not in source
    assert "getattr(sys.modules" not in source
