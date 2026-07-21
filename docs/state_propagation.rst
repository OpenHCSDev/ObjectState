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
