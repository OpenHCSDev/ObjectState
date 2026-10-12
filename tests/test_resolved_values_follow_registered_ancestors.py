"""A state's resolved values follow the states registered above it.

A step at ``plate::step`` leaves ``settings.value`` unset, so the value comes from
the plate state registered at ``plate`` when there is one and from the global
config otherwise. Which states are registered can change after the step state was
built; every read of the step must then answer from the states registered now,
whatever the order of building and registering was.

The kinds of read are kept apart (``Reads``): the stored value never changes here,
the live and saved resolved values differ while an ancestor has unsaved edits, and
the reported source names the scope and class that supplied the value.

Mutations covered: an ancestor registered after the descendant was built (in every
order of registering the two), unregistered (alone, with its descendants, by
clearing the registry), registered again with another value, replaced at its scope,
registered with unsaved edits; an ancestor's value edited, saved and restored; the
descendant's ``scope_id`` moved under another ancestor; a context entered after
the build. The three cases at the end of the file are known to fail and say why.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    build_context_stack,
    config_context,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
    set_live_global_config,
)


@dataclass
class Settings:
    value: str | None = None
    other: str | None = None


@dataclass
class GlobalConfig:
    settings: Settings = field(default_factory=Settings)


mark_global_config_type(GlobalConfig)
LazySettings = LazyDataclassFactory.make_lazy_simple(Settings)


@dataclass
class Holder:
    """A plate or a step: one lazy ``Settings``."""

    settings: LazySettings = field(default_factory=LazySettings)


GLOBAL, PLATE, OTHER_PLATE, STEP = "", "plate", "other", "plate::step"
PATH = "settings.value"


class Reads(NamedTuple):
    """Every kind of read of ``settings.value`` on one state."""

    stored: str | None  # what the state's own parameters hold
    stored_on_object: str | None  # the raw field of the object the state builds
    uncached: str | None  # plain attribute access on that object among today's ancestors
    attribute: str | None  # plain attribute access through ``state.fields``
    live: str | None  # get_resolved_value
    live_object: str | None  # attribute of to_resolved_object()
    saved: str | None  # get_saved_resolved_value
    saved_object: str | None  # attribute of to_saved_resolved_object()
    source: tuple | None  # get_provenance: (scope, class) that supplied the live value
    dirty: frozenset  # fields whose live and saved resolved values differ


def _reads(state: ObjectState) -> Reads:
    built = state.to_object()
    ancestors = ObjectStateRegistry.get_ancestor_objects_with_scopes(state.scope_id)
    with build_context_stack(built, ancestors, state.scope_id):
        uncached = built.settings.value
    return Reads(
        stored=state.parameters[PATH],
        stored_on_object=object.__getattribute__(built.settings, "value"),
        uncached=uncached,
        attribute=state.fields.settings.value,
        live=state.get_resolved_value(PATH),
        live_object=state.to_resolved_object().settings.value,
        saved=state.get_saved_resolved_value(PATH),
        saved_object=state.to_saved_resolved_object().settings.value,
        source=state.get_provenance(PATH),
        dirty=frozenset(state.dirty_fields),
    )


def _inherited(live: str, scope: str, *, saved: str | None = None) -> Reads:
    """The reads of a state that stores nothing and inherits from ``scope``."""
    saved = live if saved is None else saved
    return Reads(
        stored=None,
        stored_on_object=None,
        uncached=live,
        attribute=live,
        live=live,
        live_object=live,
        saved=saved,
        saved_object=saved,
        source=(scope, Settings),
        dirty=frozenset() if live == saved else frozenset({PATH}),
    )


FROM_GLOBAL = _inherited("global", GLOBAL)


def _plate_state(value: str, scope: str = PLATE) -> ObjectState:
    return ObjectState(Holder(settings=LazySettings(value=value)), scope_id=scope)


def _step_state() -> ObjectState:
    return ObjectState(Holder(), scope_id=STEP)


@pytest.fixture(autouse=True)
def _global_config_and_empty_registry():
    ObjectStateRegistry.clear()
    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, GlobalConfig(settings=Settings(value="global")))
    yield
    ObjectStateRegistry.clear()


STEP_REGISTRATION = ("never", "before the plate", "after the plate")


@pytest.fixture(params=STEP_REGISTRATION)
def step_and_plate(request):
    """A step state built before its plate is registered, then the plate registered.

    The step state itself is never registered, or registered before or after the
    plate: a state reads its ancestors from the registry in all three cases.
    """
    step = _step_state()
    assert _reads(step) == FROM_GLOBAL
    plate = _plate_state("plate")
    if request.param == "before the plate":
        ObjectStateRegistry.register(step)
    ObjectStateRegistry.register(plate)
    if request.param == "after the plate":
        ObjectStateRegistry.register(step)
    return step, plate


def test_ancestor_registered_after_the_descendant_was_built_supplies_the_value(step_and_plate):
    step, _ = step_and_plate
    assert _reads(step) == _inherited("plate", PLATE)


def test_both_orders_of_building_give_the_same_reads(step_and_plate):
    late_ancestor_step, _ = step_and_plate
    ancestor_first_step = _step_state()
    assert _reads(late_ancestor_step) == _reads(ancestor_first_step)


@pytest.mark.parametrize(
    "remove",
    [
        lambda plate: ObjectStateRegistry.unregister(plate),
        lambda plate: ObjectStateRegistry.unregister_scope_and_descendants(PLATE),
        lambda plate: ObjectStateRegistry.clear(),
    ],
    ids=["unregister", "unregister_scope_and_descendants", "clear"],
)
def test_unregistering_the_ancestor_takes_its_value_back(step_and_plate, remove):
    step, plate = step_and_plate
    assert _reads(step) == _inherited("plate", PLATE)
    remove(plate)
    assert _reads(step) == FROM_GLOBAL


def test_ancestor_registered_again_with_another_value(step_and_plate):
    step, plate = step_and_plate
    assert _reads(step) == _inherited("plate", PLATE)

    ObjectStateRegistry.unregister(plate)
    ObjectStateRegistry.register(_plate_state("second"))
    assert _reads(step) == _inherited("second", PLATE)

    # Replaced at its scope without unregistering first.
    ObjectStateRegistry.register(_plate_state("third"))
    assert _reads(step) == _inherited("third", PLATE)

    # The first state again, as it was.
    ObjectStateRegistry.register(plate)
    assert _reads(step) == _inherited("plate", PLATE)


def test_ancestor_registered_with_unsaved_edits_separates_live_from_saved():
    step = _step_state()
    ObjectStateRegistry.register(step)
    plate = _plate_state("plate")
    plate.update_parameter(PATH, "edited")

    ObjectStateRegistry.register(plate)

    assert step.dirty_fields == {PATH}  # materialised at registration, before any read
    assert _reads(step) == _inherited("edited", PLATE, saved="plate")


def test_registered_descendant_is_told_at_registration_and_unregistration():
    step = _step_state()
    ObjectStateRegistry.register(step)
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)

    plate = _plate_state("plate")
    ObjectStateRegistry.register(plate)
    assert changes == [{PATH}]

    ObjectStateRegistry.unregister(plate)
    assert changes == [{PATH}, {PATH}]


def test_registration_that_changes_no_ancestor_resolves_nothing_again():
    plate = _plate_state("plate")
    ObjectStateRegistry.register(plate)
    step = _step_state()
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)
    live_snapshot = step._live_resolved
    before = _reads(step)

    ObjectStateRegistry.register(step)  # the state itself
    ObjectStateRegistry.register(_plate_state("elsewhere", OTHER_PLATE))  # not above it
    ObjectStateRegistry.register(_step_state_at(f"{PLATE}::sibling"))  # beside it

    assert _reads(step) == before
    assert step._live_resolved is live_snapshot
    assert changes == []


def _step_state_at(scope: str) -> ObjectState:
    return ObjectState(Holder(), scope_id=scope)


def test_edit_save_and_restore_of_a_late_registered_ancestor(step_and_plate):
    step, plate = step_and_plate
    ObjectStateRegistry.register(step)

    plate.update_parameter(PATH, "edited")
    assert _reads(step) == _inherited("edited", PLATE, saved="plate")

    plate.mark_saved()
    assert _reads(step) == _inherited("edited", PLATE)

    plate.update_parameter(PATH, "again")
    assert _reads(step) == _inherited("again", PLATE, saved="edited")

    plate.restore_saved()
    assert _reads(step) == _inherited("edited", PLATE)


def test_field_edited_in_the_ancestor_before_it_was_registered_is_not_lost():
    """A field invalidated on the descendant and a changed ancestor in one read."""
    step = _step_state()
    ObjectStateRegistry.register(step)
    step.invalidate_field("settings.other")

    ObjectStateRegistry.clear()
    ObjectStateRegistry._states[PLATE] = ObjectState(
        Holder(settings=LazySettings(value="plate", other="other")), scope_id=PLATE
    )  # put in place without telling any state, as time travel does

    assert step.get_resolved_value("settings.other") == "other"
    assert _reads(step) == _inherited("plate", PLATE)


def test_scope_moved_under_another_ancestor(step_and_plate):
    step, _ = step_and_plate
    ObjectStateRegistry.register(_plate_state("elsewhere", OTHER_PLATE))

    step.scope_id = f"{OTHER_PLATE}::step"
    assert _reads(step) == _inherited("elsewhere", OTHER_PLATE)

    step.scope_id = STEP
    assert _reads(step) == _inherited("plate", PLATE)


def test_context_entered_after_the_build_changes_no_read(step_and_plate):
    step, _ = step_and_plate
    expected = _inherited("plate", PLATE)
    assert _reads(step) == expected

    with config_context(Holder(settings=LazySettings(value="ambient")), scope_id="ambient"):
        inside = _reads(step)

    # ``uncached`` is resolved inside the entered context on purpose; see the last
    # test in this file for what that shows.
    assert inside._replace(uncached="plate") == expected
    assert _reads(step) == expected


# --- Known to fail --------------------------------------------------------------
# The three cases below are the same kind of fault (a resolved snapshot outliving
# something it was computed from) with another input than registration. Comparing
# registered ancestors does not cover them; issue #53 says why each is open.

OPEN = "open, see https://github.com/OpenHCSDev/ObjectState/issues/53: "


@pytest.mark.xfail(strict=True, reason=OPEN + "only registered states are told of an ancestor edit")
def test_unregistered_descendant_follows_an_edit_of_its_ancestor(step_and_plate):
    step, plate = step_and_plate
    ObjectStateRegistry.unregister(step)
    assert _reads(step) == _inherited("plate", PLATE)

    plate.update_parameter(PATH, "edited")

    assert _reads(step) == _inherited("edited", PLATE, saved="plate")


@pytest.mark.xfail(strict=True, reason=OPEN + "no state is told when the global config is replaced")
def test_global_config_replaced_after_the_build():
    step = _step_state()
    ObjectStateRegistry.register(step)

    set_live_global_config(GlobalConfig, GlobalConfig(settings=Settings(value="replaced")))

    assert _reads(step) == _inherited("replaced", GLOBAL, saved="global")


@pytest.mark.xfail(strict=True, reason=OPEN + "a state resolved inside a context keeps its values")
def test_resolving_inside_an_entered_context_does_not_take_its_values():
    entered = Holder(settings=LazySettings(value="ambient"))
    with config_context(entered, scope_id="ambient"):
        step = _step_state()

    assert _reads(step) == FROM_GLOBAL
