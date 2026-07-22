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
~~~~~~~~~~~~~~~~~~~~~~~
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

Initial values and nested defaults
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``ObjectState(..., initial_values=...)`` accepts authored callable kwargs at
construction. A nested dataclass value is projected through the same flat-path
owner used during normal extraction, so its container and every registered
dotted child start in agreement. ObjectState records the analyzer-derived
declared default for both nested containers and leaves. Resetting an authored
nested override therefore restores the callable's concrete dataclass default;
a lazy container whose declared default is ``None`` still resets to ``None``.

Callers updating an existing state should use their normal ObjectState editing
or code-document service so removed kwargs travel through
``reset_parameter()``. They must not flatten dataclass fields independently.

Structural subfield semantics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A tuple, list, or nested dataclass remains one writable ObjectState owner field.
``subfield_semantics(DottedFieldPath(...))`` projects display identities for its
structural leaves without registering those cells as a second set of state
fields. Each ``ObjectStateSubfieldSemantic`` retains the raw, live resolved,
saved resolved, and signature-default values together with explicit presence
bits, so a concrete ``None`` is not confused with a missing leaf.

Leaf ``dirty`` state compares live resolved and saved resolved values.
``signature_diff`` compares raw state with the signature default, and
``inherited_value`` identifies a missing raw leaf supplied by resolution. The
returned ``semantic_markers`` use ``*`` for dirty and ``_`` for either a
signature difference or inherited value. UI tables consume this projection;
they do not recompute those predicates or write individual cells back to
ObjectState.

When an owner value changes, ObjectState reports the exact structural display
paths that changed, such as ``filters[0].match_type``. The owner field remains
the persistence and update boundary.

Lifecycle
~~~~~~~~~
ObjectStates are created when an object is added, persist independently of UI windows, and
are removed when unregistered from the registry.

Windows should attach to the existing state instead of creating a new state for
each editor. A caller that needs a fail-loud editing boundary can wrap the state
in ``ObjectStateEditSession``. The session delegates updates to ObjectState and
reconstructs the edited object through ``to_object()``; it does not introduce a
second saved/live model.

ObjectStateRegistry
-------------------

Purpose
~~~~~~~
Singleton registry of all ObjectStates, keyed by ``scope_id``. Supports lookup, ancestry
traversal, and history management.

Registration
~~~~~~~~~~~~
- ``register(state)`` / ``unregister(state)``
- ``unregister_scope_and_descendants(scope_id)`` for an owned scope subtree
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
