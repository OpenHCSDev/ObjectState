# Changelog

## 4.0.1

Requires `python-introspect>=0.3.0,<0.4` (was `<0.3`). ObjectState does not call
python-introspect's JSON codec (`to_jsonable`, `dataclass_from_mapping`), so nothing
it stores or sends changes form.

## 4.0.0

The global config has one holder (#56). While a state whose object is of the
global config type is registered at the global scope (`scope_id=""`), that state
holds the global config: the live global config is the object its parameters
describe and the saved one is the object it last saved. While no such state is
registered, the object given to `set_global_config` is both. The global config is
one value per process; threads no longer each have their own.

Removed, and what to call instead:

- `ensure_global_config_context(config_type, config)` (also
  `objectstate.lazy_factory.ensure_global_config_context`): call
  `set_global_config(config_type, config)`. Not needed at all beside a registered
  global state: registering the state makes its object the global config.
- `set_global_config_for_editing(config_type, config)`: call
  `set_global_config(config_type, config)`.
- `set_live_global_config(config_type, config)`: with a registered global state,
  edit the state (`state.update_parameter(path, value)`); the live global config
  follows. Without one there is no separate live value; call `set_global_config`.
- `set_saved_global_config(config_type, config)`: with a registered global state,
  save it (`state.mark_saved()`); to replace the object, live and saved, call
  `state.update_object_instance(config)` or `set_global_config`. Without one, call
  `set_global_config`.
- `get_current_global_config(config_type, use_live=...)`: call
  `get_live_global_config(config_type)` or `get_saved_global_config(config_type)`.
- `clear_current_temp_global()`: nothing; no library code leaves the caller's
  entered context any more. Leave a `config_context` block to leave its context.
- `objectstate.global_config.GlobalContextValues`: with a registered global state,
  checkpoint the state (`ObjectStateTransactionCheckpoint.capture(state)` /
  `.restore(state)`). Without one, keep `get_live_global_config(config_type)` and
  put it back with `set_global_config`, or `forget_stored_global_config` when it
  was `None`.
- `ObjectState.prepare_history_global_context()`: nothing; read
  `get_live_global_config` / `get_saved_global_config`.
- `objectstate.lazy_factory.rebuild_lazy_config_with_new_global_reference(...)`:
  nothing (it had no caller; it copied a lazy config and stored a global config as
  a side effect).
- `ObjectStateRegistry._resolve_again_below` is now `resolve_again_below`.

Added: `set_global_config`, `forget_stored_global_config(config_type)` (a session
reset or a test that must leave nothing stored), `ObjectStateRegistry.global_config_state(config_type)`;
`get_live_global_config` and `get_saved_global_config` are exported from
`objectstate`.

Behaviour changes:

- `set_global_config` while a global state is registered replaces that state's
  object (`update_object_instance`): unsaved edits of the global state are dropped
  and its descendants are told at once. A call that only repeated what the state
  already held must be deleted, not kept.
- `set_global_config` without a global state tells registered states at once (the
  setters used to tell nobody until the next read).
- Registering a global state makes its object the global config at once, also when
  nothing was stored before. Unregistering it makes the global config what
  `set_global_config` last stored while no state held it (or the declared defaults).
- Every thread reads the same global config. A thread that used to see the declared
  defaults because nothing was stored in it now sees the process's global config.
- Editing, replacing, restoring or time-travelling the global state no longer
  leaves the caller's entered `config_context`: a block entered before the change
  keeps the layers it was entered with until it is left.
- A global state that is not registered no longer changes the global config when it
  is edited, saved, restored or given another object.
- `get_live_global_config` returns the object the registered global state builds
  from its parameters (one object until the next change), not the instance the
  application first passed in. Compare values, not identity.
