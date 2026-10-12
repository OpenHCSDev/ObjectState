"""The global config: the value every resolution starts from.

There is one global config per config type per process, read in two ways: live
(with unsaved edits) and saved. One thing holds it:

- the state registered at the global scope (``scope_id=""``), when its object is
  of that type. The live global config is the object its parameters describe and
  the saved global config is the object it last saved. Editing, saving, restoring
  or time-travelling that state is editing, saving, restoring or time-travelling
  the global config; nothing else has to be told.
- otherwise the object given to ``set_global_config``. Nothing edits it, so its
  live and saved reads are the same object. A process that registers no state
  (a compile worker, an execution server, a script) uses only this.

``set_global_config`` is the one way to replace the global config from outside.
While a state holds it, the call replaces that state's object
(``ObjectState.update_object_instance``), so the state, its descendants and their
subscribers all follow; a stored object the state would disagree with cannot be
created. A stored object is not read while a state holds the global config, and is
read again, unchanged, once that state is no longer registered.

Threads play no part: the registry is one per process and so is the stored
object, so every thread reads the same global config.
"""

from typing import Any

from objectstate.scope_key import ScopeKey

# What ``set_global_config`` stored while no state held the global config.
_stored_global_configs: dict[type, Any] = {}


_registry_class: Any = None


def _registry():
    """``ObjectStateRegistry``, imported on first use (its module imports this one's users)."""
    global _registry_class
    if _registry_class is None:
        from objectstate.object_state_registry import ObjectStateRegistry

        _registry_class = ObjectStateRegistry
    return _registry_class


def _state_holding(config_type: type):
    return _registry().global_config_state(config_type)


def set_global_config(config_type: type, config: Any) -> None:
    """Make ``config`` the global config of ``config_type``, live and saved.

    With a state of that type registered at the global scope this replaces the
    state's object and its unsaved edits; without one it stores ``config``. Either
    way the registered states that inherit from it are told at once.
    """
    if not isinstance(config_type, type):
        raise TypeError(f"Global config key must be a type, got {config_type!r}.")
    if not isinstance(config, config_type):
        raise TypeError(
            f"Global config value for {config_type.__name__} must be an "
            f"instance of that type, got {type(config).__name__}."
        )
    state = _state_holding(config_type)
    if state is None:
        _stored_global_configs[config_type] = config
        _registry().resolve_again_below((ScopeKey(""),))
    else:
        state.update_object_instance(config)


def forget_stored_global_config(config_type: type) -> None:
    """Store no global config of ``config_type`` any more (a session reset, a test).

    This is the stored object only. A state that holds the global config is
    unregistered through the registry, not here.
    """
    if _stored_global_configs.pop(config_type, None) is not None:
        _registry().resolve_again_below((ScopeKey(""),))


def get_live_global_config(config_type: type) -> Any | None:
    """The global config with unsaved edits, or ``None`` when there is none."""
    state = _state_holding(config_type)
    if state is None:
        return _stored_global_configs.get(config_type)
    return state.object_for_resolution()


def get_saved_global_config(config_type: type) -> Any | None:
    """The global config as last saved, or ``None`` when there is none."""
    state = _state_holding(config_type)
    if state is None:
        return _stored_global_configs.get(config_type)
    return state.object_for_resolution(use_saved=True)
