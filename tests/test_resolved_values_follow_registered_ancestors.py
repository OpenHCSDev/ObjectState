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
under another ancestor. Only the fields a change can reach are resolved again.

A context the caller has entered is not one of the sources: the second half of the
file runs one sequence of builds, edits, saves and replacements outside any context
and inside several kinds of entered context, and requires the same reads and the
same notifications. A lazy object that no state owns does resolve against the
entered context. The last section saves the state of the global config and stores
the saved global config in both orders.
"""

import gc
import threading
import weakref
from contextlib import ExitStack, nullcontext
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
    get_live_global_config,
    get_saved_global_config,
    mark_global_config_type,
    resolve_with_provenance,
    set_base_config_type,
    set_global_config,
    spawn_thread_with_context,
)

from objectstate.context_manager import get_context_layer_stack
from objectstate.inspection import FieldInspection


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
    set_global_config(GlobalConfig, GlobalConfig(settings=Settings(value="global")))
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
    inspection = FieldInspection.of(step, PATH)
    assert inspection.field_name == "value"
    assert inspection.provenance.field_name == "value"


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


def _replace_global(value: str) -> None:
    set_global_config(GlobalConfig, GlobalConfig(settings=Settings(value=value)))


def _register_global_state() -> ObjectState:
    """From here on the global config is this state's: an edit is live, a save is saved."""
    global_state = ObjectState(get_live_global_config(GlobalConfig), scope_id=GLOBAL)
    ObjectStateRegistry.register(global_state)
    return global_state


@pytest.mark.parametrize("registered", [True, False], ids=["registered", "not registered"])
def test_global_config_replaced_after_the_build(registered):
    step = _step_state()
    if registered:
        ObjectStateRegistry.register(step)
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)

    _replace_global("replaced")
    assert _reads(step) == _inherited("replaced", GLOBAL)
    assert changes == [{PATH}]

    global_state = _register_global_state()
    assert _reads(step) == _inherited("replaced", GLOBAL)
    global_state.update_parameter(PATH, "edited")
    assert _reads(step) == _inherited("edited", GLOBAL, saved="replaced")

    _replace_global("replaced again")  # replaces the object of the state
    assert _reads(step) == _inherited("replaced again", GLOBAL)
    assert global_state.parameters[PATH] == "replaced again"
    assert changes == [{PATH}, {PATH}, {PATH}]


def test_global_config_replaced_with_equal_values_resolves_nothing(resolved_fields):
    step = _step_state()
    live_snapshot = step._live_resolved
    resolved_fields.clear()

    set_global_config(GlobalConfig, GlobalConfig(settings=Settings(value="global")))

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
    assert step.dirty_fields == {"settings.other"}

    plate.update_parameter(PATH, "plate again")
    assert _reads(step) == _inherited("plate again", PLATE, saved="replaced")._replace(
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

    global_state.mark_saved()
    assert _reads(step) == _inherited("typed", GLOBAL)


def _plain_read() -> str | None:
    """A lazy object no state owns, read in a context entered from the global config."""
    with config_context(Holder()):
        return LazySettings().value


def test_every_thread_reads_the_same_global_config(step_under_plate, resolved_fields):
    """The global config is one per process, like the registry.

    A thread reads the values the state has without resolving anything again, and
    a global config a thread sets is the global config of every thread. Nothing here
    is synchronised, so the threads run one after the other.
    """
    step, plate = step_under_plate
    plate.update_parameter(PATH, None)
    expected = (step.get_resolved_value(PATH), step.get_saved_resolved_value(PATH))
    assert expected == ("global", "plate")
    changes: list[set[str]] = []
    step.on_resolved_changed(changes.append)
    resolved_fields.clear()
    seen: list[tuple] = []

    def read():
        seen.append(
            (
                step.get_resolved_value(PATH),
                step.get_saved_resolved_value(PATH),
                _plain_read(),
            )
        )

    def set_and_read():
        _replace_global("other thread")
        read()

    def in_a_thread(target):
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()

    in_a_thread(read)
    assert seen == [(*expected, "global")]
    assert resolved_fields == [] and changes == []

    in_a_thread(set_and_read)
    assert seen[1] == ("other thread", "plate", "other thread")
    assert (step.get_resolved_value(PATH), _plain_read()) == ("other thread", "other thread")
    assert changes == [{PATH}]

    in_a_thread(lambda: plate.update_parameter(PATH, "from a thread"))
    assert step.get_resolved_value(PATH) == "from a thread"


# --- A context the caller has entered is not a source ---------------------------
# A state resolves against the global config, the states registered above it and its
# own object. ``config_context`` blocks entered around a build, a read or a change
# supply nothing, whatever they hold and whatever scope they claim.

OTHER_PATH = "settings.other"
AMBIENT = "ambient"  # a scope where no state is registered


def _ambient(value: str = "ambient", **entered):
    return config_context(
        Holder(settings=LazySettings(value=value, other=f"{value} other")), **entered
    )


def _nested():
    contexts = ExitStack()
    contexts.enter_context(_ambient("outer", scope_id="outer"))
    contexts.enter_context(_ambient("inner", scope_id="inner"))
    return contexts


def _ambient_global_config():
    return config_context(
        GlobalConfig(settings=Settings(value="ambient", other="ambient other")), scope_id=GLOBAL
    )


ENTERED = {
    "one context": lambda: _ambient(scope_id=AMBIENT),
    "without a scope id": _ambient,
    "under the scope of a registered ancestor": lambda: _ambient(scope_id=PLATE),
    "under the scope of the state itself": lambda: _ambient(scope_id=STEP),
    "under the global scope": lambda: _ambient(scope_id=GLOBAL),
    "a global config": _ambient_global_config,
    "masking the layers outside it": lambda: _ambient(scope_id=AMBIENT, mask_with_none=True),
    "started from the saved global config": lambda: _ambient(
        scope_id=AMBIENT, use_live_global=False
    ),
    "nested": _nested,
}


def _start_over() -> None:
    ObjectStateRegistry.clear()
    set_base_config_type(GlobalConfig)
    set_global_config(GlobalConfig, GlobalConfig(settings=Settings(value="global")))


def _history(entered) -> list:
    """Every read and notification of three steps while their sources change inside ``entered()``.

    One step is built and registered before the block, one is built inside it and
    never registered, one is built inside it and first read after it.
    """
    plate = ObjectState(Holder(settings=LazySettings(other="plate other")), scope_id=PLATE)
    ObjectStateRegistry.register(plate)
    global_state = _register_global_state()
    states: dict[str, ObjectState] = {}
    told: list[tuple] = []
    history: list[tuple] = []

    def follow(name: str, state: ObjectState) -> ObjectState:
        states[name] = state
        state.on_resolved_changed(lambda paths: told.append((name, "resolved", frozenset(paths))))
        state.on_state_changed(lambda paths: told.append((name, "state", frozenset(paths))))
        return state

    def record(event: str) -> None:
        registered = {state.scope_id for state in ObjectStateRegistry.get_all()} | {GLOBAL}
        seen = {}
        for name, state in states.items():
            # ``dirty_fields`` first: it is a read like the others and must not need one.
            dirty = frozenset(state.dirty_fields)
            other = (
                state.get_resolved_value(OTHER_PATH),
                state.get_saved_resolved_value(OTHER_PATH),
                state.get_provenance(OTHER_PATH),
            )
            seen[name] = (dirty, _reads(state), other)
            for path in (PATH, OTHER_PATH):
                source = state.get_provenance(path)
                assert source is None or source[0] in registered, (event, name, path, source)
        history.append((event, seen, tuple(told)))

    before = follow("built before", _step_state())
    ObjectStateRegistry.register(before)
    record("before the block")

    with entered():
        follow("built inside", _step_state_at(f"{PLATE}::inside"))
        late = _step_state_at(f"{PLATE}::late")
        record("built")

        global_state.update_parameter(PATH, "replaced")
        record("global config replaced")

        plate.update_parameter(PATH, "edited")
        record("ancestor edited")

        plate.mark_saved()
        record("ancestor saved")

        plate.update_parameter(OTHER_PATH, None)
        record("ancestor gives a field up")

        global_state.update_parameter(PATH, "saved too")
        global_state.mark_saved()
        record("saved global config replaced")

        before.invalidate_cache()
        record("every field resolved again")

        with _ambient("deeper", scope_id="deeper"):
            plate.update_parameter(PATH, "edited deeper")
            record("ancestor edited one block further in")

        ObjectStateRegistry.unregister(plate)
        record("ancestor unregistered")

        ObjectStateRegistry.register(plate)
        record("ancestor registered again")

        before.update_parameter(PATH, "own")
        record("own value set")

        before.update_parameter(PATH, None)
        before.mark_saved()
        record("own value given up and saved")

        plate.restore_saved()
        record("ancestor restored")

        plate.update_parameter(PATH, None)
        plate.mark_saved()
        global_state.update_parameter(PATH, "typed")
        record("global state edited")

        global_state.mark_saved()
        record("global state saved")

        global_state.update_parameter(PATH, "given up")
        global_state.restore_saved()
        record("global state restored")

        _replace_global("set from outside")
        record("global config set from outside")

        ObjectStateRegistry.unregister(global_state)
        record("global state unregistered")

    follow("first read after the block", late)
    record("after the block")
    return history


def test_the_changes_of_the_history_are_seen_outside_any_context():
    """The sequence the next test repeats inside contexts does change what is read."""
    history = {event: seen for event, seen, _ in _history(nullcontext)}

    def value_reads(event: str) -> set:
        return {reads for _, reads, _ in history[event].values()}

    assert value_reads("built") == {FROM_GLOBAL}
    assert value_reads("global config replaced") == {
        _inherited("replaced", GLOBAL, saved="global")
    }
    assert value_reads("ancestor edited") == {_inherited("edited", PLATE, saved="global")}
    assert value_reads("ancestor saved") == {_inherited("edited", PLATE)}
    assert {other for _, _, other in history["ancestor saved"].values()} == {
        ("plate other", "plate other", (PLATE, Settings))
    }
    assert {other for _, _, other in history["ancestor gives a field up"].values()} == {
        (None, "plate other", (GLOBAL, Settings))
    }
    assert value_reads("ancestor unregistered") == {_inherited("saved too", GLOBAL)}
    assert value_reads("global state edited") == {_inherited("typed", GLOBAL, saved="saved too")}
    assert value_reads("global state saved") == {_inherited("typed", GLOBAL)}
    assert value_reads("global state restored") == {_inherited("typed", GLOBAL)}
    assert value_reads("global config set from outside") == {
        _inherited("set from outside", GLOBAL)
    }
    # What was stored before the state was registered is the global config again.
    assert value_reads("global state unregistered") == {FROM_GLOBAL}
    assert value_reads("after the block") == {FROM_GLOBAL}


@pytest.mark.parametrize("entered", ENTERED)
def test_reads_and_notifications_inside_an_entered_context_are_those_outside(entered):
    outside = _history(nullcontext)
    _start_over()

    assert _history(ENTERED[entered]) == outside


def test_resolving_inside_an_entered_context_does_not_take_its_values():
    with _ambient(scope_id=AMBIENT):
        step = _step_state()
        assert _reads(step) == FROM_GLOBAL

    assert _reads(step) == FROM_GLOBAL


def test_layers_a_state_resolves_against_start_from_the_global_config(step_under_plate):
    step, plate = step_under_plate
    ancestors = ObjectStateRegistry.get_ancestor_objects_with_scopes(step.scope_id)

    with _nested():
        entered = get_context_layer_stack()
        with build_context_stack(step.to_object(), ancestors, step.scope_id):
            layers = get_context_layer_stack().layers
            assert [(layer.scope_id, layer.obj) for layer in layers] == [
                (GLOBAL, get_live_global_config(GlobalConfig)),
                *ancestors,
                (STEP, step.to_object()),
            ]
            assert ancestors[0] == (PLATE, plate.to_object())
        assert get_context_layer_stack() is entered

        with pytest.raises(ZeroDivisionError):
            with build_context_stack(step.to_object(), ancestors, step.scope_id):
                1 / 0
        assert get_context_layer_stack() is entered


def test_lazy_object_no_state_owns_resolves_against_the_entered_context(step_under_plate):
    """Plain attribute access reads the entered context, before and after a state resolves in it."""
    step, plate = step_under_plate
    plain = LazySettings()

    with _ambient(scope_id=AMBIENT):
        entered = get_context_layer_stack()

        def reads_the_entered_context() -> None:
            assert (plain.value, Holder().settings.other) == ("ambient", "ambient other")
            assert tuple(resolve_with_provenance(LazySettings, "value")) == (
                "ambient",
                AMBIENT,
                Settings,
            )
            assert get_context_layer_stack() is entered

        reads_the_entered_context()

        built_inside = _step_state_at(f"{PLATE}::inside")
        assert _reads(built_inside) == _inherited("plate", PLATE)
        reads_the_entered_context()

        plate.update_parameter(PATH, "edited")
        assert step.get_resolved_value(PATH) == "edited"
        reads_the_entered_context()

        step.invalidate_cache()
        _replace_global("replaced")
        assert step.get_resolved_value(PATH) == "edited"
        reads_the_entered_context()

        with _ambient("inner", scope_id="inner"):
            assert built_inside.get_provenance(PATH) == (PLATE, Settings)
            assert plain.value == "inner"
        reads_the_entered_context()


def test_context_entered_in_another_thread_is_not_a_source():
    entered, read = threading.Event(), threading.Event()

    def hold_a_context() -> None:
        with _ambient(scope_id=AMBIENT):
            entered.set()
            read.wait(timeout=10)

    thread = threading.Thread(target=hold_a_context)
    thread.start()
    try:
        assert entered.wait(timeout=10)
        assert _reads(_step_state()) == FROM_GLOBAL
    finally:
        read.set()
        thread.join()


def test_thread_started_with_the_entered_context_reads_states_as_outside():
    """``spawn_thread_with_context`` copies the entered context into the thread."""
    step = _step_state()
    seen: list = []

    def read() -> None:
        seen.extend([LazySettings().value, _reads(step), _reads(_step_state())])

    with _ambient(scope_id=AMBIENT):
        spawn_thread_with_context(read).join()

    assert seen == ["ambient", FROM_GLOBAL, FROM_GLOBAL]


