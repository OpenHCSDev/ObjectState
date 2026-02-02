State Management
================

This page documents the core state primitives: :class:`objectstate.object_state.ObjectState`
and :class:`objectstate.object_state.ObjectStateRegistry`. The API is generic—no OpenHCS
references—and reflects the current implementation in ``objectstate/object_state.py``.

ObjectState
-----------

Purpose
~~~~~~~
A UI-friendly model extracted from a backing object (dataclass, callable, etc.) that
authoritatively stores working parameters and resolved values across a window's lifecycle.

Core attributes
~~~~~~~~~~~~~~~
- ``object_instance``: the backing object (updated on save via ``to_object()``)
- ``parameters``: flat dict of user-editable values (dotted paths for nested dataclasses)
- ``_live_resolved``: last resolved values using the *current* ancestor stack
- ``_saved_resolved``: resolved values at the last explicit save (baseline)
- ``_saved_parameters``: immutable snapshot of raw parameters at save time
- ``_live_provenance``: dict tracking which scope provided each inherited field value
- ``scope_id``: unique key for registry lookup

Saved vs Live
~~~~~~~~~~~~~
- ``_saved_resolved`` represents "on disk" (after last save).
- ``_live_resolved`` represents "on screen" (after every edit and ancestor change).
- ``mark_saved()`` updates saved baselines from current live values.
- ``restore_saved()`` resets working values back to the saved snapshot.
- ``dirty_fields`` tracks where ``_live_resolved`` differs from ``_saved_resolved`` (resolved / inherited view).
- ``is_raw_dirty`` is a fast check for unsaved edits in raw parameters (``parameters`` vs ``_saved_parameters``).

Reading resolved values
~~~~~~~~~~~~~~~~~~~~~~
ObjectState keeps both a *live* resolved snapshot and a *saved* resolved snapshot.
Use the appropriate accessor depending on whether you want to include unsaved edits:

- ``get_resolved_value(name)``: returns the live resolved value from ``_live_resolved`` (includes unsaved edits)
- ``get_saved_resolved_value(name)``: returns the saved resolved value from ``_saved_resolved`` (excludes unsaved edits)

Key methods
~~~~~~~~~~~
- ``mark_saved()``: set current state as the new baseline
- ``restore_saved()``: revert parameters/resolved values to saved baseline
- ``dirty_fields``: resolved diffs (live vs saved) as a set of dotted field names
- ``is_raw_dirty``: true if raw parameters differ from saved parameters
- ``to_object()``: materialize a concrete object from the current parameters

Lifecycle
~~~~~~~~~
ObjectStates are created when an object is added, persist independently of UI windows, and
are removed when unregistered from the registry.

ObjectStateRegistry
-------------------

Purpose
~~~~~~~
Singleton registry of all ObjectStates, keyed by ``scope_id``. Supports lookup, ancestry
traversal, and history management.

Registration
~~~~~~~~~~~~
- ``register(state)`` / ``unregister(scope_id)``
- ``get_by_scope(scope_id)``
- ``get_ancestor_objects(scope_id)`` / ``get_ancestor_objects_with_scopes(scope_id)``

Saved vs Live pattern (registry-wide)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The registry coordinates saved/live baselines across all ObjectStates so that
application code can distinguish "proposed" vs "committed" values while showing
immediate UI feedback.

Notes
~~~~~
- Registry methods are classmethods; the registry is effectively a singleton.
- History/undo is covered separately in :doc:`undo_redo`.
- Provenance tracking for inherited fields is covered in :doc:`provenance`.
