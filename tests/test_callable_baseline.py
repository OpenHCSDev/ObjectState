"""Tests for callable identity handling in ObjectState baselines."""

from dataclasses import dataclass
from typing import ClassVar

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    set_base_config_type,
    set_global_config_for_editing,
)


def _reset_registry_and_history() -> None:
    ObjectStateRegistry._states.clear()
    ObjectStateRegistry._time_travel_limbo.clear()
    ObjectStateRegistry._graveyard.clear()
    ObjectStateRegistry._snapshots.clear()
    ObjectStateRegistry._timelines.clear()
    ObjectStateRegistry._current_timeline = "main"
    ObjectStateRegistry._current_head = None
    ObjectStateRegistry._in_time_travel = False
    ObjectStateRegistry._atomic_depth = 0
    ObjectStateRegistry._atomic_label = None
    ObjectStateRegistry._atomic_triggering_scope = None


class RebuiltCallable:
    """Callable wrapper whose deepcopy would otherwise create a new identity."""

    def __call__(self, image=None):
        return image

    def __reduce__(self):
        return (RebuiltCallable, ())


class StepLike:
    """Minimal step-shaped object with a callable declaration field."""

    callable_parameter_name: ClassVar[str] = "func"

    def __init__(self, func=None, name="step"):
        self.func = func
        self.name = name

    @classmethod
    def callable_parameter(cls) -> str:
        return cls.callable_parameter_name


def _threshold_function(image=None, threshold: float = 1.0):
    """Threshold an image."""
    return image


@dataclass(frozen=True)
class NestedBounds:
    minimum: float = 0.0


@dataclass(frozen=True)
class NestedOptions:
    threshold: float = 1.0
    bounds: NestedBounds = NestedBounds()


def _nested_options_function(
    image=None,
    options: NestedOptions = NestedOptions(),
):
    return image


def test_function_parameter_paths_record_callable_owner():
    state = ObjectState(_threshold_function, scope_id="plate::step::function_0")

    assert state.type_for_path("threshold") is _threshold_function
    assert state.get_resolved_value("threshold") == 1.0


def test_initial_values_flatten_nested_dataclass_overrides():
    options = NestedOptions(
        threshold=7.0,
        bounds=NestedBounds(minimum=2.0),
    )

    state = ObjectState(
        _nested_options_function,
        scope_id="plate::step::function_0",
        initial_values={"options": options},
    )

    assert state.parameters["options"] == options
    assert state.parameters["options.threshold"] == 7.0
    assert state.parameters["options.bounds"] == options.bounds
    assert state.parameters["options.bounds.minimum"] == 2.0
    assert state.signature_default("options") == NestedOptions()
    assert state.reconstruct_top_level_parameters() == {
        "image": None,
        "options": options,
    }


def test_saved_baseline_preserves_callable_identity_values():
    func = RebuiltCallable()

    state = ObjectState(StepLike(func=func), scope_id="plate::step")

    assert state._saved_parameters[StepLike.callable_parameter()] is func
    assert state.dirty_fields == set()
    assert state.is_raw_dirty is False


def test_one_shot_saved_resolution_detaches_mutables_and_preserves_callable_identity():
    @dataclass
    class Options:
        values: list[str]

    class Submitted:
        def __init__(self, func, options: Options):
            self.func = func
            self.options = options

    func = RebuiltCallable()
    original = Submitted(func, Options(["saved"]))
    resolved, provenance = ObjectState.resolve_saved_object(original)

    class DelegatingOwner:
        __objectstate_delegate__ = "declaration"

        def __init__(self, declaration):
            self.declaration = declaration

    delegated, _ = ObjectState.resolve_saved_object(DelegatingOwner(original))
    assert resolved.func is func
    assert isinstance(delegated, Submitted)
    assert delegated.func is func
    assert provenance == {}
    original.options.values.append("later")
    assert resolved.options.values == ["saved"]
    assert delegated.options.values == ["saved"]
    resolved.options.values.append("compiled")
    assert original.options.values == ["saved", "later"]


def test_one_shot_saved_resolution_detaches_inherited_alias_graph():
    @dataclass
    class Options:
        values: list[str] | None = None
        mirror: list[str] | None = None
        func: object = None

    LazyOptions = LazyDataclassFactory.make_lazy_simple(Options)

    @dataclass
    class GlobalConfig:
        options: Options

    @dataclass
    class Pipeline:
        options: Options

    @dataclass
    class Submitted:
        options: LazyOptions

    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, GlobalConfig(Options()))
    shared = ["saved"]
    func = RebuiltCallable()
    ancestor = Pipeline(Options(shared, shared, func))
    resolved, provenance = ObjectState.resolve_saved_object(
        Submitted(LazyOptions()),
        scope_id="captured::step",
        ancestor_objects_with_scopes=[("captured", ancestor)],
    )
    assert resolved.options.func is func
    assert resolved.options.values is resolved.options.mirror
    assert resolved.options.values is not shared
    assert provenance["options.values"] == ("captured", Options)
    shared.append("later")
    assert resolved.options.values == ["saved"]
    resolved.options.values.append("compiled")
    assert resolved.options.mirror == ["saved", "compiled"]
    assert shared == ["saved", "later"]


def test_time_travel_preserves_clean_callable_identity_baseline():
    _reset_registry_and_history()
    state = ObjectState(StepLike(func=RebuiltCallable()), scope_id="plate::step")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    ObjectStateRegistry.record_snapshot("clean", scope_id=state.scope_id)
    clean_id = ObjectStateRegistry.get_branch_history()[-1].id
    snapshot_state = ObjectStateRegistry._snapshots[clean_id].all_states[state.scope_id]
    callable_parameter = StepLike.callable_parameter()
    assert (
        snapshot_state.parameters[callable_parameter]
        is snapshot_state.saved_parameters[callable_parameter]
    )

    state.update_parameter("name", "changed")
    assert state.is_raw_dirty is True

    assert ObjectStateRegistry.time_travel_to_snapshot(clean_id)
    assert state.parameters[callable_parameter] is state._saved_parameters[callable_parameter]
    assert state.is_raw_dirty is False
