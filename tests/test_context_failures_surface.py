"""A context that cannot be built must fail; it must never run with a layer missing."""

from dataclasses import dataclass, field

import pytest

from objectstate import (
    LazyDataclassFactory,
    build_context_stack,
    config_context,
    mark_global_config_type,
    merge_configs,
    set_base_config_type,
    set_global_config_for_editing,
)
from objectstate.context_manager import (
    NoActiveContextError,
    context_layer_stack,
    get_current_temp_global,
)
from objectstate.dual_axis_resolver import resolve_with_provenance


@dataclass
class Policy:
    value: int | None = 1


@dataclass
class CheckedGlobal:
    """Global config whose constructor rejects a negative worker count."""

    workers: int = 1
    policy: Policy = field(default_factory=Policy)

    def __post_init__(self):
        if self.workers < 0:
            raise ValueError("workers must not be negative")


@dataclass
class Pipeline:
    workers: int = 1


@pytest.fixture
def checked_global():
    set_base_config_type(CheckedGlobal)
    saved = CheckedGlobal()
    set_global_config_for_editing(CheckedGlobal, saved)
    return saved


def test_build_context_stack_sets_nothing_until_entered_and_resets_on_exit(checked_global):
    pipeline = Pipeline(workers=5)
    before = (get_current_temp_global(), context_layer_stack.get())

    pending = build_context_stack(
        Policy(), ancestor_objects_with_scopes=[("plate", pipeline)], current_scope_id="step"
    )
    assert (get_current_temp_global(), context_layer_stack.get()) == before

    with pending:
        assert get_current_temp_global().workers == 5
        scopes = [layer.scope_id for layer in context_layer_stack.get().layers]
        assert scopes == ["", "plate", "step"]

    assert (get_current_temp_global(), context_layer_stack.get()) == before


def test_build_context_stack_resets_when_the_block_raises(checked_global):
    before = (get_current_temp_global(), context_layer_stack.get())
    with pytest.raises(KeyError):
        with build_context_stack(Pipeline(workers=5), current_scope_id="step"):
            raise KeyError("block failed")
    assert (get_current_temp_global(), context_layer_stack.get()) == before


def test_build_context_stack_rejects_ancestors_without_scopes(checked_global):
    with pytest.raises(TypeError):
        build_context_stack(Pipeline(), ancestor_objects=[Pipeline()])


def test_layer_that_cannot_be_merged_raises(checked_global):
    with pytest.raises(ValueError, match="workers must not be negative"):
        with config_context(Pipeline(workers=-1)):
            pytest.fail("the block ran without the layer's overrides")


def test_merge_configs_that_cannot_be_applied_raises(checked_global):
    with pytest.raises(ValueError, match="workers must not be negative"):
        merge_configs(checked_global, {"workers": -1})


def test_global_type_that_cannot_be_constructed_raises():
    @dataclass
    class RequiredGlobal:
        workers: int

    mark_global_config_type(RequiredGlobal)
    set_base_config_type(RequiredGlobal)
    set_global_config_for_editing(RequiredGlobal, RequiredGlobal(workers=2))

    with pytest.raises(TypeError, match="workers"):
        with build_context_stack(RequiredGlobal(workers=3), current_scope_id=""):
            pytest.fail("the block ran without the global layer")


def test_layer_whose_configs_cannot_be_extracted_raises(checked_global):
    @dataclass
    class Unrelated:
        value: int = 9

    @dataclass
    class Step:
        step_policy: Policy

    lazy_policy = LazyDataclassFactory.make_lazy_simple(Policy)
    mistyped_step = Step(step_policy=Unrelated())

    with config_context(mistyped_step, scope_id="plate::step"):
        with pytest.raises(TypeError, match="Step.step_policy declares Policy"):
            resolve_with_provenance(lazy_policy, "value")


def test_resolver_method_without_active_context_raises():
    lazy_policy = LazyDataclassFactory.make_lazy_simple(Policy)
    assert get_current_temp_global() is None
    with pytest.raises(NoActiveContextError):
        lazy_policy(value=None)._resolve_field_value("value")
