State Propagation and Parent Notification
=========================================

``ObjectState.forward_to_parent_state()`` lets one independently scoped state
notify a parent state that a conceptual field changed. It is a callback bridge,
not a second mutation or persistence path.

Scope hierarchy is not dataclass hierarchy
-------------------------------------------

Nested dataclasses are flattened inside one ``ObjectState`` and updated with a
dotted path. They do not need parent forwarding:

.. code-block:: python

   from dataclasses import dataclass, field

   from objectstate import ObjectState

   @dataclass
   class Palette:
       background: str = "black"

   @dataclass
   class DisplayConfig:
       palette: Palette = field(default_factory=Palette)

   state = ObjectState(DisplayConfig(), scope_id="display")
   state.update_parameter("palette.background", "white")

By contrast, two objects with distinct lifecycles may have independent states
whose scopes form a parent/child relationship. The child can use its
``parent_state`` for ancestor context and can notify the parent when the parent
view owns a summary or preview of that child.

Explicit parent notification
----------------------------

.. code-block:: python

   from dataclasses import dataclass

   from objectstate import ObjectState

   @dataclass
   class Collection:
       summary: str = ""

   @dataclass
   class Entry:
       value: int = 0

   parent = ObjectState(Collection(), scope_id="collection")
   child = ObjectState(
       Entry(),
       scope_id="collection::entry_0",
       parent_state=parent,
   )

   parent.on_resolved_changed(lambda paths: print(paths))
   child.forward_to_parent_state("summary")
   # {'summary'}

The method requires a parent state. It guards against reentrant forwarding and
calls the parent's resolved-change callbacks with the chosen path. It does not
write to the parent's ``parameters`` or advance either saved baseline.

Field-path selection
--------------------

The notification path is selected in this order:

1. the explicit ``field_path`` argument;
2. the child's internal parent-field binding, when its composing owner set one;
3. the last ``scope_id`` segment, with a numeric suffix removed.

Prefer an explicit field path at public composition boundaries. The scope-based
fallback is useful for conventional child scopes such as ``entry_0``, but scope
naming is not structural dataclass ownership.

Navigation and flashing
-----------------------

Parent resolved-change callbacks may refresh a summary, request navigation, or
flash a parent-owned target. Those are view-layer reactions. ObjectState owns
only the notification and reentrancy contract; UI code remains responsible for
mapping the reported field path to widgets.

Use parent forwarding when all of the following are true:

* child and parent are independently scoped states;
* the parent presents information derived from the child; and
* an ordinary child callback cannot update that parent presentation directly.

For a nested dataclass field in the same state, call ``update_parameter()`` on
the dotted path instead.

.. _state-resolution-inputs:

What a resolved value is computed from
--------------------------------------

A resolved value of a state depends only on the state's place in the registered
hierarchy. It is computed from three things: which states are registered at the
scopes above it, what each of them stores for the field's config type and field name,
and what the global config stores. Nothing else is an input. In particular a
``config_context`` that the caller has entered is not: a state built, read or resolved
again inside such a block has the values, saved values, reported sources, dirty
fields and notifications it has outside it, during the block and after it. The state
resolves against a layer stack of its own (``build_context_stack``) that starts from
the global config and holds the registered ancestors and the state's object; the
caller's context is set aside while it does and is active again afterwards. So the
reported source of a resolved value is always a scope where a state is registered, or
``""`` for the global config.

This is the only statement of the rule. A lazy config object that no state owns is a
different route: plain attribute access on it resolves against whatever
``config_context`` is entered (see ``context_system.rst`` in the package docs), which
is how a compiler resolves a pipeline's objects.

Each resolved snapshot (live
and saved) keeps the objects it was computed from (``ResolutionSources``): the global
config instance of the thread that resolved it and the object of every state
registered above. Every resolved read (``get_resolved_value``,
``get_saved_resolved_value``, ``get_provenance``, ``to_resolved_object``,
``state.fields``, ``dirty_fields``) first compares those objects with the ones the state would be given
now. When they are the same objects the read answers from the snapshot. When one is
another object, the two are compared field by field, the way field resolution reads a
context layer, and only the fields of the state that are unset and can inherit a
differing ``(config type, field)`` are resolved again. When other scopes have a
registered state than before, every field is.

So no caller announces a change. Registering, unregistering or replacing an ancestor,
editing, saving, restoring, undoing or redoing an ancestor's value, and replacing the
global config with ``set_global_config`` all reach
a state on its next read, whether the state is registered or not. A registered state
is also told at once, so its subscribers hear of the change without a read; a state
that is not registered is referenced by nothing and tells its subscribers on its next
read.

Limits:

- Objects are compared by identity. A source that is changed in place is not seen.
  ``ObjectState.to_object`` returns the same function object for a state that wraps a
  plain function, so states registered below a function-backed state follow its edits
  only through the registry (that is, when they are registered themselves).
- Nothing is synchronised. Every thread reads the same registry and the same global
  config, so a thread that edits while another reads must be kept apart by the
  application (in a GUI: edit in the GUI thread).

The state of the global config
------------------------------

The global config is the value every resolution starts from. There is one per config
type per process, read as edited (live) and as saved, and one thing holds it
(``objectstate.global_config``):

- The state registered at the global scope (``scope_id=""``) whose object is of that
  type. The live global config is the object its parameters describe
  (``object_for_resolution()``) and the saved global config is the object it last
  saved. Nothing copies them anywhere: ``get_live_global_config``,
  ``get_saved_global_config``, ``config_context`` and every state's resolution ask the
  registered state. So an edit, a save, a restore, a replaced object, an undo or a
  redo of that state is that change of the global config, and its registered
  descendants are told at once.
- While no such state is registered: the object given to ``set_global_config``. Nothing
  edits it, so the live and the saved read are the same object. A process without
  states (a compile worker, an execution server, a script) uses only this.

Registering the global state is all it takes to make its object the global config; no
``set_global_config`` call is needed beside it. Unregistering it (or travelling to a
point in history where it was not registered) ends that at once: the global config is
then again what ``set_global_config`` last stored while no state held it, or the
declared defaults.

``set_global_config(config_type, config)`` is the one way to replace the global config
from outside. While a state holds the global config the call is
``state.update_object_instance(config)``: the state takes the new object as its live
and saved value (unsaved edits are dropped) and its descendants and their subscribers
follow. A stored object that disagrees with a registered global state cannot be made.

Threads play no part. The registry is one per process and so is the stored object, so
a worker thread reads the global config the GUI thread edits, with or without
``spawn_thread_with_context`` (which copies the entered ``config_context`` layers, not
the global config, into the new thread).

A ``config_context`` block entered before the global config changes keeps the layers
it was entered with until it is left.


