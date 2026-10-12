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
global config with ``set_live_global_config`` / ``set_saved_global_config`` all reach
a state on its next read, whether the state is registered or not. A registered state
is also told at once, so its subscribers hear of the change without a read; a state
that is not registered is referenced by nothing and tells its subscribers on its next
read.

Limits:

- Objects are compared by identity. A source that is changed in place is not seen.
  ``ObjectState.to_object`` returns the same function object for a state that wraps a
  plain function, so states registered below a function-backed state follow its edits
  only through the registry (that is, when they are registered themselves).
- The global config is stored per thread. A snapshot follows the global config of the
  thread that resolved it; a read from another thread answers from the snapshot and
  does not resolve it again for that thread's global config.

The state of the global config
------------------------------

The global config is stored per thread, once as edited (live) and once as saved. A
state whose object is a global config writes that store when its own object changes:
``update_parameter`` applies the edit to the live global config,
``mark_saved`` stores the saved object as the saved global config, ``restore_saved``
stores the saved object as the live one again, ``update_object_instance`` and time
travel store both. Each is stored before any descendant resolves again, so saving the
global state is one call: its registered descendants resolve their saved values
against the object just saved and are told at once.

``set_live_global_config``, ``set_saved_global_config`` and
``ensure_global_config_context`` (both at once) store a global config where no state
does it: at startup before a state exists, and in a thread or process that resolves
plain lazy objects without a registry, such as a compile worker. Calling one with the
values the global state has just stored, before or after ``mark_saved``, changes
nothing. A setter tells no state; states find the replaced object on their next read.

