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
registered with unsaved edits; an ancestor's value edited, saved, restored, undone
and redone, one and two levels up, with the descendant registered or not; the
global config replaced through its setters; the descendant's ``scope_id`` moved
under another ancestor; a context entered after the build. Only the fields a change
can reach are resolved again. The case at the end of the file is known to fail and
says why.
"""

import gc
import threading
import weakref
from dataclasses import dataclass, field
from typing import NamedTuple

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    build_context_stack,
    config_context,
    dual_axis_resolver,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
    set_live_global_config,
    set_saved_global_config,
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


# --- Sources other than registration --------------------------------------------
# A resolved snapshot is computed from the global config and from the objects of
# the states registered above the state. The cases below change one of those
# without changing which states are registered. No registered state has to be told:
# the state finds the difference on its next read, registered or not, and resolves
# only the fields that the difference can reach.


def test_unregistered_descendant_follows_edit_save_and_restore_of_its_ancestor(step_and_plate):
    step, plate = step_and_plate
    ObjectStateRegistry.unregister(step)
    assert _reads(step) == _inherited("plate", PLATE)

    plate.update_parameter(PATH, "edited")
    assert _reads(step) == _inherited("edited", PLATE, saved="plate")

    plate.mark_saved()
    assert _reads(step) == _inherited("edited", PLATE)

    plate.update_parameter(PATH, "again")
    assert _reads(step) == _inherited("again", PLATE, saved="edited")

    plate.restore_saved()
    assert _reads(step) == _inherited("edited", PLATE)


def test_undo_and_redo_of_an_ancestor_edit(step_and_plate):
    step, plate = step_and_plate
    with ObjectStateRegistry.atomic("edit plate", scope_id=PLATE):
        plate.update_parameter(PATH, "first")
    with ObjectStateRegistry.atomic("edit plate", scope_id=PLATE):
        plate.update_parameter(PATH, "second")
    assert _reads(step) == _inherited("second", PLATE, saved="plate")

    assert ObjectStateRegistry.time_travel_back()
    assert _reads(step) == _inherited("first", PLATE, saved="plate")

    assert ObjectStateRegistry.time_travel_forward()
    assert _reads(step) == _inherited("second", PLATE, saved="plate")


def test_unregistered_descendant_is_told_on_its_next_read(step_and_plate):
    step, plate = step_and_plate
    ObjectStateRegistry.unregister(step)
    resolved: list[set[str]] = []
    state: list[set[str]] = []
    step.on_resolved_changed(resolved.append)
    step.on_state_changed(state.append)

    plate.update_parameter(PATH, "edited")
    assert resolved == [] and state == []  # nothing holds the state to tell it

    assert step.get_resolved_value(PATH) == "edited"
    assert resolved == [{PATH}] and state == [{PATH}]
    assert step.dirty_fields == {PATH}

    assert step.get_resolved_value(PATH) == "edited"
    assert resolved == [{PATH}] and state == [{PATH}]


def test_unregistered_descendant_is_not_kept_alive():
    plate = _plate_state("plate")
    ObjectStateRegistry.register(plate)
    step = _step_state()
    plate.update_parameter(PATH, "edited")
    assert step.get_resolved_value(PATH) == "edited"
    plate.update_parameter(PATH, "again")
    gone = weakref.ref(step)

    del step
    gc.collect()

    assert gone() is None


@pytest.fixture(params=["registered", "not registered"])
def step_under_plate(request):
    """A plate that sets ``value`` and ``other``, and a step below it that sets neither."""
    plate = ObjectState(
        Holder(settings=LazySettings(value="plate", other="plate other")), scope_id=PLATE
    )
    ObjectStateRegistry.register(plate)
    step = _step_state()
    if request.param == "registered":
        ObjectStateRegistry.register(step)
    return step, plate


@pytest.fixture
def resolved_fields(monkeypatch):
    """The ``(config type, field)`` of every field resolution, in order."""
    calls: list[tuple[type, str]] = []
    resolve = dual_axis_resolver.resolve_with_provenance

    def counting(container_type, field_name):
        calls.append((container_type, field_name))
        return resolve(container_type, field_name)

    monkeypatch.setattr(dual_axis_resolver, "resolve_with_provenance", counting)
    return calls


def test_only_the_edited_field_is_resolved_again(step_under_plate, resolved_fields):
    step, plate = step_under_plate
    assert step.get_saved_resolved_value(PATH) == "plate"
    resolved_fields.clear()

    plate.update_parameter("settings.other", "edited other")
    assert step.get_resolved_value("settings.other") == "edited other"
    assert step.get_resolved_value(PATH) == "plate"
    assert step.get_saved_resolved_value("settings.other") == "plate other"
    assert step.dirty_fields == {"settings.other"}

    assert [name for _, name in resolved_fields] == ["other"]
    assert _reads(step) == _inherited("plate", PLATE)._replace(dirty={"settings.other"})


def test_a_field_the_descendant_sets_itself_is_not_resolved_again(resolved_fields):
    plate = _plate_state("plate")
    ObjectStateRegistry.register(plate)
    step = ObjectState(Holder(settings=LazySettings(value="own")), scope_id=STEP)
    resolved_fields.clear()

    plate.update_parameter(PATH, "edited")
    plate.mark_saved()
    plate.update_parameter(PATH, "again")

    assert step.get_resolved_value(PATH) == "own"
    assert step.get_saved_resolved_value(PATH) == "own"
    assert step.get_provenance(PATH) is None
    assert step.dirty_fields == set()
    # ``mark_saved`` changes the saved sources and the saved snapshot is resolved in
    # full, but a field with its own value is never asked of the context.
    assert [call for call in resolved_fields if call[1] == "value"] == []


def test_reading_an_unchanged_state_resolves_nothing(step_under_plate, resolved_fields):
    step, _ = step_under_plate
    live_snapshot, saved_snapshot = step._live_resolved, step._saved_resolved
    resolved_fields.clear()

    assert _reads(step)._replace(uncached=None) == _inherited("plate", PLATE)._replace(
        uncached=None
    )

    assert resolved_fields == []
    assert step._live_resolved is live_snapshot
    assert step._saved_resolved is saved_snapshot


INNER = f"{STEP}::inner"


@pytest.mark.parametrize("registered", [(), (STEP,), (INNER,), (STEP, INNER)], ids=str)
def test_edit_two_levels_up(registered):
    plate = _plate_state("plate")
    ObjectStateRegistry.register(plate)
    step, inner = _step_state(), _step_state_at(INNER)
    for state in (step, inner):
        if state.scope_id in registered:
            ObjectStateRegistry.register(state)
    assert _reads(inner) == _inherited("plate", PLATE)

    plate.update_parameter(PATH, "edited")
    assert _reads(inner) == _inherited("edited", PLATE, saved="plate")

    # The state between them takes the value over, then gives it back.
    step.update_parameter(PATH, "step")
    expected_source = STEP if STEP in registered else PLATE
    expected_value = "step" if STEP in registered else "edited"
    assert _reads(inner) == _inherited(expected_value, expected_source, saved="plate")

    step.update_parameter(PATH, None)
    plate.mark_saved()
    assert _reads(inner) == _inherited("edited", PLATE)


def _replace_global(value: str, *, live: bool = True, saved: bool = False) -> None:
    config = GlobalConfig(settings=Settings(value=value))
    if live:
        set_live_global_config(GlobalConfig, config)
    if saved:
        set_saved_global_config(GlobalConfig, config)


@pytest.mark.parametrize("registered", [True, False], ids=["registered", "not registered"])
def test_global_config_replaced_after_the_build(registered):
    step = _step_state()
    if registered:
        ObjectStateRegistry.register(step)
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)

    _replace_global("replaced")
    assert _reads(step) == _inherited("replaced", GLOBAL, saved="global")
    assert changes == [{PATH}]

    _replace_global("saved too", saved=True)
    assert _reads(step) == _inherited("saved too", GLOBAL)

    _replace_global("only saved", live=False, saved=True)
    assert _reads(step) == _inherited("saved too", GLOBAL, saved="only saved")

    set_global_config_for_editing(GlobalConfig, GlobalConfig(settings=Settings(value="both")))
    assert _reads(step) == _inherited("both", GLOBAL)
    assert changes == [{PATH}, {PATH}, {PATH}]


def test_global_config_replaced_with_equal_values_resolves_nothing(resolved_fields):
    step = _step_state()
    live_snapshot = step._live_resolved
    resolved_fields.clear()

    set_global_config_for_editing(GlobalConfig, GlobalConfig(settings=Settings(value="global")))

    assert step.get_resolved_value(PATH) == "global"
    assert step.get_saved_resolved_value(PATH) == "global"
    assert resolved_fields == []
    assert step._live_resolved is live_snapshot


def test_global_config_replaced_then_an_ancestor_edited(step_under_plate, resolved_fields):
    step, plate = step_under_plate
    plate.update_parameter(PATH, None)  # the plate inherits ``value`` too
    assert _reads(step) == _inherited("global", GLOBAL, saved="plate")
    plate.mark_saved()
    assert _reads(step) == _inherited("global", GLOBAL)
    resolved_fields.clear()

    _replace_global("replaced")
    plate.update_parameter("settings.other", "edited other")

    assert step.get_resolved_value(PATH) == "replaced"
    assert step.get_resolved_value("settings.other") == "edited other"
    assert step.get_provenance(PATH) == (GLOBAL, Settings)
    assert step.get_provenance("settings.other") == (PLATE, Settings)
    assert step.dirty_fields == {PATH, "settings.other"}

    plate.update_parameter(PATH, "plate again")
    assert _reads(step) == _inherited("plate again", PLATE, saved="global")._replace(
        dirty={PATH, "settings.other"}
    )


def test_global_state_edit_reaches_states_two_levels_down(step_under_plate):
    step, plate = step_under_plate
    plate.update_parameter(PATH, None)
    plate.mark_saved()
    global_state = ObjectState(GlobalConfig(settings=Settings(value="global")), scope_id=GLOBAL)
    ObjectStateRegistry.register(global_state)

    global_state.update_parameter(PATH, "typed")
    assert _reads(step) == _inherited("typed", GLOBAL, saved="global")

    # Saving the global state does not store the saved global config; the
    # application does, with the setter.
    global_state.mark_saved()
    set_saved_global_config(GlobalConfig, global_state.to_object())
    assert _reads(step) == _inherited("typed", GLOBAL)


def test_another_thread_does_not_make_a_state_resolve_again(step_under_plate, resolved_fields):
    """The global config is stored per thread; a snapshot follows the thread it was resolved in.

    A thread started without one (``threading.Thread`` copies no thread-local value)
    reads the values the state has, and a thread that sets its own does not change
    them. The registry's stores are one per process and not synchronised, so the
    threads here run one after the other.
    """
    step, plate = step_under_plate
    plate.update_parameter(PATH, None)
    expected = (step.get_resolved_value(PATH), step.get_saved_resolved_value(PATH))
    assert expected == ("global", "plate")
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)
    resolved_fields.clear()
    seen: list[tuple] = []

    def read_without_a_global_config():
        seen.append((step.get_resolved_value(PATH), step.get_saved_resolved_value(PATH)))

    def read_with_its_own_global_config():
        set_global_config_for_editing(
            GlobalConfig, GlobalConfig(settings=Settings(value="other thread"))
        )
        read_without_a_global_config()

    for target in (read_without_a_global_config, read_with_its_own_global_config):
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()

    assert seen == [expected, expected]
    assert (step.get_resolved_value(PATH), step.get_saved_resolved_value(PATH)) == expected
    assert resolved_fields == [] and changes == []

    # An ancestor edit is followed from any thread: ancestors are one per process.
    thread = threading.Thread(target=lambda: plate.update_parameter(PATH, "from a thread"))
    thread.start()
    thread.join()
    assert step.get_resolved_value(PATH) == "from a thread"


# --- Known to fail --------------------------------------------------------------
# Open in issue #53: an owner decision on whether a state's values may depend on a
# context the caller has entered.

OPEN = "open, see https://github.com/OpenHCSDev/ObjectState/issues/53: "


@pytest.mark.xfail(strict=True, reason=OPEN + "a state resolved inside a context keeps its values")
def test_resolving_inside_an_entered_context_does_not_take_its_values():
    entered = Holder(settings=LazySettings(value="ambient"))
    with config_context(entered, scope_id="ambient"):
        step = _step_state()

    assert _reads(step) == FROM_GLOBAL
