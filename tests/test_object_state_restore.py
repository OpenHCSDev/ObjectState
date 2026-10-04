"""ObjectState restore lifecycle tests."""

from dataclasses import dataclass, field

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    get_live_global_config,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)
from objectstate.global_config import set_live_global_config


def test_restore_saved_resets_live_global_context_for_descendants():
    """Canceling a global edit must clear both ObjectState and live context."""

    @dataclass
    class GlobalConfig:
        threshold: int = 1

    mark_global_config_type(GlobalConfig)
    set_base_config_type(GlobalConfig)
    LazyGlobalConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)

    saved_global = GlobalConfig(threshold=1)
    set_global_config_for_editing(GlobalConfig, saved_global)

    global_state = ObjectState(saved_global, scope_id="")
    child_state = ObjectState(LazyGlobalConfig(), scope_id="plate::step")
    ObjectStateRegistry.register(global_state, _skip_snapshot=True)
    ObjectStateRegistry.register(child_state, _skip_snapshot=True)

    global_state.update_parameter("threshold", 5)
    assert get_live_global_config(GlobalConfig).threshold == 5
    assert child_state.get_resolved_value("threshold") == 5
    assert child_state.dirty_fields == {"threshold"}

    global_state.restore_saved()

    assert global_state.parameters["threshold"] == 1
    assert get_live_global_config(GlobalConfig).threshold == 1
    assert child_state.get_resolved_value("threshold") == 1
    assert child_state.dirty_fields == set()


def test_one_shot_saved_resolution_uses_saved_scope_without_editing_lifecycle(monkeypatch):
    @dataclass
    class Policy:
        value: int = 1

    LazyPolicy = LazyDataclassFactory.make_lazy_simple(Policy)

    @dataclass
    class GlobalConfig:
        policy: Policy = field(default_factory=Policy)

    @dataclass
    class Pipeline:
        policy: LazyPolicy = field(default_factory=LazyPolicy)

    @dataclass
    class Step:
        policy: LazyPolicy = field(default_factory=LazyPolicy)

    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, GlobalConfig(Policy(value=3)))
    set_live_global_config(GlobalConfig, GlobalConfig(Policy(value=9)))
    authored_pipeline = Pipeline()
    submitted = Step()

    def reject_editor(*args, **kwargs):
        raise AssertionError("Headless resolution must not construct or register editors")

    monkeypatch.setattr(ObjectState, "__init__", reject_editor)
    monkeypatch.setattr(ObjectStateRegistry, "register", reject_editor)
    resolved, provenance = ObjectState.resolve_saved_object(
        submitted,
        scope_id="headless::step",
        ancestor_objects_with_scopes=[("headless", authored_pipeline)],
    )
    assert type(resolved.policy) is Policy
    assert resolved.policy.value == 3
    assert provenance["policy.value"] == ("", Policy)
    assert object.__getattribute__(submitted.policy, "value") is None

    authored_pipeline.policy.value = 7
    resolved_next, provenance_next = ObjectState.resolve_saved_object(
        submitted,
        scope_id="headless::step",
        ancestor_objects_with_scopes=[("headless", authored_pipeline)],
    )
    assert resolved_next.policy.value == 7
    assert provenance_next["policy.value"] == ("headless", Policy)
    assert resolved.policy.value == 3


def test_one_shot_saved_resolution_preserves_mro_subtypes_and_nonlazy_none():
    @dataclass
    class ParentPolicy:
        inherited: str | None = "parent-default"

    @dataclass
    class DerivedPolicy(ParentPolicy):
        own: int = 11

    LazyDerived = LazyDataclassFactory.make_lazy_simple(DerivedPolicy)

    @dataclass
    class SourceDomain:
        width: int = 5

    @dataclass
    class VolumeDomain(SourceDomain):
        depth: int = 4

    @dataclass
    class GlobalConfig:
        parent: ParentPolicy = field(default_factory=ParentPolicy)
        derived: DerivedPolicy = field(default_factory=DerivedPolicy)

    @dataclass
    class Pipeline:
        parent: ParentPolicy

    @dataclass
    class Step:
        policy: LazyDerived = field(default_factory=LazyDerived)
        domain: SourceDomain = field(default_factory=SourceDomain)
        untouched: str | None = None

    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, GlobalConfig())
    step = Step(domain=VolumeDomain())
    resolved, provenance = ObjectState.resolve_saved_object(
        step,
        scope_id="mro::step",
        ancestor_objects_with_scopes=[("mro", Pipeline(ParentPolicy("pipeline")))],
    )
    assert type(resolved.domain) is VolumeDomain
    assert resolved.domain.depth == 4
    assert resolved.untouched is None
    # A concrete same-type value beats sibling inheritance, matching the UI walk.
    assert resolved.policy.inherited == "parent-default"
    assert resolved.policy.own == 11
    assert provenance["policy.inherited"] == ("", DerivedPolicy)


def test_one_shot_saved_resolution_preserves_factory_and_constructor_effects():
    effects = []

    def default_values():
        effects.append("factory")
        return ["default"]

    @dataclass
    class Options:
        values: list[str] = field(default_factory=default_values)

    LazyOptions = LazyDataclassFactory.make_lazy_simple(Options)

    class Submitted:
        def __init__(self, options: LazyOptions):
            effects.append("constructor")
            if not options.values:
                raise ValueError("empty options")
            self.options = options

    original = Submitted(LazyOptions())
    effects.clear()
    resolved, _ = ObjectState.resolve_saved_object(original, scope_id="factory::step")
    assert resolved.options.values == ["default"]
    assert effects == ["factory", "constructor"]
    original.options.values = []
    with pytest.raises(ValueError, match="empty options"):
        ObjectState.resolve_saved_object(original, scope_id="factory::step")
