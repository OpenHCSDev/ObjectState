"""The global config has one holder.

While a state of the global config type is registered at the global scope, that
state holds the global config: the live global config is the object its parameters
describe and the saved one is the object it last saved. While none is registered,
the object given to ``set_global_config`` is both. There is nothing to keep in
step, so every history of operations must leave every reader agreeing.

The first test runs every sequence of up to three operations (edit, save and
restore of the global state, replacing its object, ``set_global_config``,
registering and unregistering it), starting with and without the state
registered, with each operation made in the calling thread or in another one.
After every operation it requires, by every kind of read:

- the global config is the holder's object, and holds the holder's values;
- a registered and an unregistered descendant read that value: stored on the
  state and on the object it builds, by attribute access, as live and saved
  resolved value, as reported source and as dirty fields;
- a lazy object no state owns reads it in a context entered from the live and
  from the saved global config;
- another thread reads the same;
- the registered descendant was told of a changed live value at once, the
  unregistered one is told the same on its next read, and neither is told
  anything when the value did not change.

A model of three values (stored, the state's live, the state's saved) predicts
the values, so agreement on a wrong value fails too. The tests after it cover
undo and redo, a global state that was never given to ``set_global_config``, and
a process that has no state at all.
"""

import itertools
import threading
from dataclasses import dataclass

import pytest

from objectstate import (
    ObjectState,
    ObjectStateRegistry,
    config_context,
    forget_stored_global_config,
    get_base_global_config,
    get_live_global_config,
    get_saved_global_config,
    set_base_config_type,
    set_global_config,
)
from objectstate import global_config as global_config_module

from .test_resolved_values_follow_registered_ancestors import (
    GLOBAL,
    PATH,
    STEP,
    GlobalConfig,
    Holder,
    LazySettings,
    Settings,
    _inherited,
    _reads,
)

DEFAULT = None  # ``Settings.value`` as declared


def _config(value: str | None) -> GlobalConfig:
    return GlobalConfig(settings=Settings(value=value))


def _in_a_thread(function):
    result: list = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(function())
        except BaseException as error:  # noqa: BLE001 - raised again by the caller
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def _plain_reads() -> tuple:
    """A lazy object no state owns, in contexts entered from the live and saved global config."""
    with config_context(Holder()):
        live = LazySettings().value
    with config_context(Holder(), use_live_global=False):
        saved = LazySettings().value
    return live, saved


def _global_config_values() -> tuple:
    """The value of the global config by each way of asking for it, live then saved."""
    live = get_live_global_config(GlobalConfig)
    saved = get_saved_global_config(GlobalConfig)
    if live is None:  # no global config: contexts start from the declared defaults
        assert saved is None
        live = saved = get_base_global_config()
        assert live == get_base_global_config(use_live=False) == GlobalConfig()
    else:
        assert get_base_global_config() is live
        assert get_base_global_config(use_live=False) is saved
    values = live.settings.value, saved.settings.value
    assert _plain_reads() == values
    return values


@dataclass
class Model:
    """What the reads must be, computed without the library."""

    stored: str | None
    live: str | None
    saved: str | None
    registered: bool

    @property
    def values(self) -> tuple:
        return (self.live, self.saved) if self.registered else (self.stored, self.stored)


class World:
    """A global state, one registered and one unregistered descendant, and the model."""

    def __init__(self, *, registered: bool, stored: bool = True) -> None:
        ObjectStateRegistry.clear()
        set_base_config_type(GlobalConfig)
        forget_stored_global_config(GlobalConfig)
        if stored:
            set_global_config(GlobalConfig, _config("stored"))
        self.model = Model("stored" if stored else DEFAULT, "initial", "initial", registered)
        self.global_state = ObjectState(_config("initial"), scope_id=GLOBAL)
        if registered:
            ObjectStateRegistry.register(self.global_state)
        self.fresh = (f"value {number}" for number in itertools.count())
        self.told: dict[str, list] = {"registered": [], "unregistered": []}
        self.descendants = {
            "registered": ObjectState(Holder(), scope_id=STEP),
            "unregistered": ObjectState(Holder(), scope_id="plate::unregistered"),
        }
        ObjectStateRegistry.register(self.descendants["registered"])
        for name, state in self.descendants.items():
            state.get_resolved_value(PATH)
            state.on_resolved_changed(
                lambda paths, name=name: self.told[name].append(frozenset(paths))
            )
        self.values = self.model.values
        self.agree("built")

    # --- operations ---------------------------------------------------------------
    def edit(self) -> None:
        self.model.live = next(self.fresh)
        self.global_state.update_parameter(PATH, self.model.live)

    def save(self) -> None:
        self.model.saved = self.model.live
        self.global_state.mark_saved()

    def restore(self) -> None:
        self.model.live = self.model.saved
        self.global_state.restore_saved()

    def replace(self) -> None:
        self.model.live = self.model.saved = next(self.fresh)
        self.global_state.update_object_instance(_config(self.model.live))

    def set(self) -> None:
        value = next(self.fresh)
        if self.model.registered:
            self.model.live = self.model.saved = value
        else:
            self.model.stored = value
        set_global_config(GlobalConfig, _config(value))

    def register(self) -> None:
        self.model.registered = True
        ObjectStateRegistry.register(self.global_state)

    def unregister(self) -> None:
        self.model.registered = False
        ObjectStateRegistry.unregister(self.global_state)

    # --- what must hold after every operation ---------------------------------------
    def agree(self, after: object) -> None:
        live_before = self.values[0]
        self.values = expected = self.model.values
        changed = [frozenset({PATH})] if expected[0] != live_before else []

        # Told at once, before anything is read.
        assert self.told["registered"] == changed, (after, "registered descendant told")
        assert self.told["unregistered"] == [], (after, "nothing holds it to tell it")

        self.holder_and_global_config_are_one(after)
        assert _global_config_values() == expected, after
        assert _in_a_thread(_global_config_values) == expected, after

        reads = _inherited(expected[0], GLOBAL, saved=expected[1])
        for name, state in self.descendants.items():
            assert _reads(state) == reads, (after, name)
            assert _in_a_thread(lambda state=state: _reads(state)) == reads, (after, name, "thread")

        # The unregistered descendant heard the same, on its read.
        assert self.told["unregistered"] == changed, (after, "unregistered descendant told")
        assert self.told["registered"] == changed, (after, "a read tells nothing more")
        for told in self.told.values():
            told.clear()

    def holder_and_global_config_are_one(self, after: object) -> None:
        holder = ObjectStateRegistry.global_config_state(GlobalConfig)
        live = get_live_global_config(GlobalConfig)
        saved = get_saved_global_config(GlobalConfig)
        stored = global_config_module._stored_global_configs.get(GlobalConfig)
        assert (stored.settings.value if stored else DEFAULT) == self.model.stored, after
        if holder is None:
            assert not self.model.registered, after
            assert live is saved is stored, after
            return
        assert holder is self.global_state and self.model.registered, after
        assert live is holder.object_for_resolution(), after
        assert saved is holder.object_for_resolution(use_saved=True), after
        assert live.settings.value == holder.parameters[PATH], after
        assert saved.settings.value == holder._saved_parameters[PATH], after
        assert live is get_live_global_config(GlobalConfig), (after, "one object until a change")
        dirty = {PATH} if self.model.live != self.model.saved else set()
        assert holder.dirty_fields == dirty, after


OPERATIONS = ("edit", "save", "restore", "replace", "set", "register", "unregister")


def _histories(length: int):
    for size in range(1, length + 1):
        yield from itertools.product(OPERATIONS, repeat=size)


@pytest.fixture(autouse=True)
def _empty_registry_and_no_stored_global_config():
    yield
    ObjectStateRegistry.clear()
    forget_stored_global_config(GlobalConfig)


@pytest.mark.parametrize("registered", [True, False], ids=["state registered", "no state"])
@pytest.mark.parametrize("threaded", [False, True], ids=["calling thread", "another thread"])
def test_every_reader_agrees_after_every_history(registered: bool, threaded: bool):
    for history in _histories(3 if not threaded else 2):
        world = World(registered=registered)
        for position, operation in enumerate(history):
            act = getattr(world, operation)
            _in_a_thread(act) if threaded else act()
            world.agree((history, position))


def test_registering_a_global_state_is_all_it_takes():
    """No ``set_global_config`` call: the registered state's object is the global config."""
    world = World(registered=False, stored=False)
    assert get_live_global_config(GlobalConfig) is None
    assert world.values == (DEFAULT, DEFAULT)

    world.register()
    world.agree("registered")
    assert world.values == ("initial", "initial")

    world.edit()
    world.agree("edited")
    world.unregister()
    world.agree("unregistered")
    assert get_live_global_config(GlobalConfig) is None
    assert world.values == (DEFAULT, DEFAULT)

    world.set()
    world.agree("stored")
    forget_stored_global_config(GlobalConfig)
    world.model.stored = DEFAULT
    world.agree("stored object forgotten")  # registered states are told at once


def test_a_process_without_states_reads_what_was_set():
    """A compile worker or a script: no state, plain lazy objects only, any thread."""
    ObjectStateRegistry.clear()
    set_base_config_type(GlobalConfig)
    set_global_config(GlobalConfig, _config("set"))
    assert _global_config_values() == ("set", "set")
    assert _in_a_thread(_global_config_values) == ("set", "set")

    _in_a_thread(lambda: set_global_config(GlobalConfig, _config("set in a thread")))
    assert _global_config_values() == ("set in a thread", "set in a thread")


def test_a_context_entered_before_a_global_edit_keeps_what_it_was_entered_with():
    """Editing the global state no longer leaves the caller's context."""
    world = World(registered=True)
    with config_context(Holder()):
        assert LazySettings().value == "initial"
        world.edit()
        assert LazySettings().value == "initial"
        with config_context(Holder()):
            assert LazySettings().value == "initial"
        # States do not read the entered context: they follow the edit inside it too.
        assert world.descendants["registered"].get_resolved_value(PATH) == world.model.live
    world.agree("edited inside a context")


def test_global_state_of_another_type_does_not_hold_this_global_config():
    world = World(registered=False)
    other = ObjectState(Holder(settings=LazySettings(value="not a global config")), scope_id=GLOBAL)
    ObjectStateRegistry.register(other)
    assert ObjectStateRegistry.global_config_state(GlobalConfig) is None
    assert get_live_global_config(GlobalConfig).settings.value == "stored"
    world.set()
    assert get_live_global_config(GlobalConfig).settings.value == world.model.stored


# --- Undo and redo ----------------------------------------------------------------


def _recorded(world: World, operation: str) -> tuple:
    with ObjectStateRegistry.atomic(operation, scope_id=GLOBAL):
        getattr(world, operation)()
    world.agree(operation)
    return world.model.values


@pytest.mark.parametrize(
    "operations",
    [
        ("edit", "edit", "save", "edit"),
        ("edit", "save", "edit", "restore"),
        ("edit", "replace", "edit", "save"),
        ("edit", "set", "edit"),
    ],
    ids=" ".join,
)
def test_undo_and_redo_move_the_global_config_with_the_state(operations):
    world = World(registered=True)
    ObjectStateRegistry.record_snapshot("start", GLOBAL)
    timeline = [world.model.values]
    timeline += [_recorded(world, operation) for operation in operations]

    def travelled_to(index: int, direction: str) -> None:
        world.model.live, world.model.saved = timeline[index]
        world.agree((direction, index))

    for index in reversed(range(len(timeline) - 1)):
        assert ObjectStateRegistry.time_travel_back()
        travelled_to(index, "back")
    for index in range(1, len(timeline)):
        assert ObjectStateRegistry.time_travel_forward()
        travelled_to(index, "forward")

    # Operations after time travel start from where it ended.
    for operation in ("edit", "save", "restore", "set", "unregister", "register"):
        getattr(world, operation)()
        world.agree(("after time travel", operation))


def test_time_travel_to_before_the_global_state_was_registered():
    """Without its state the global config is again what was stored; redo brings the state back."""
    world = World(registered=False)
    ObjectStateRegistry.record_snapshot("no global state", STEP)
    with ObjectStateRegistry.atomic("register the global state", scope_id=GLOBAL):
        world.register()
    world.agree("registered")
    with ObjectStateRegistry.atomic("edit", scope_id=GLOBAL):
        world.edit()
    world.agree("edited")
    edited = world.model.live

    assert ObjectStateRegistry.time_travel_back()
    world.model.live = "initial"
    world.agree("back to the registration")

    assert ObjectStateRegistry.time_travel_back()
    world.model.registered = False
    world.agree("back to before the registration")
    assert world.values == ("stored", "stored")

    assert ObjectStateRegistry.time_travel_forward()
    world.model.registered = True
    world.agree("forward to the registration")

    assert ObjectStateRegistry.time_travel_forward()
    world.model.live = edited
    world.agree("forward to the edit")
