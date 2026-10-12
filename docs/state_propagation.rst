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

What a resolved value is computed from
--------------------------------------

A resolved value of a state is computed from three things: which states are
registered at the scopes above it, what each of them stores for the field's config
type and field name, and what the global config stores. Each resolved snapshot (live
and saved) keeps the objects it was computed from (``ResolutionSources``): the global
config instance of the thread that resolved it and the object of every state
registered above. Every resolved read (``get_resolved_value``,
``get_saved_resolved_value``, ``get_provenance``, ``to_resolved_object``,
``state.fields``) first compares those objects with the ones the state would be given
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
- A state built or resolved inside a ``config_context`` the caller entered takes that
  context's layers into its snapshot and keeps them after the block
  (`issue #53 <https://github.com/OpenHCSDev/ObjectState/issues/53>`_).

