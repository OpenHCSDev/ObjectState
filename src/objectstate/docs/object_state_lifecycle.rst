ObjectState Lifecycle and Contracts
===================================

Purpose
-------

``ObjectState`` is the UI-independent model for editing and resolving one
backing object. A form manager may attach to an existing state, but opening or
closing a window does not define that state's lifetime.

Flat ownership
--------------

One ``ObjectState`` owns one flat parameter mapping. Nested dataclasses are
walked during extraction and represented by dotted paths such as
``display.palette.background``. They are not represented by recursively owned
``ObjectState`` instances.

Container fields remain the writable boundary. Structural leaves of a tuple,
list, or nested dataclass are display projections returned by
``subfield_semantics()``. A table can render those leaves and their dirty,
signature-difference, or inherited markers, but must update the owning field
through ``update_parameter()``.

Lifecycle
---------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Boundary
     - Contract
   * - Backing object creation
     - Create and register its ``ObjectState`` at the same ownership boundary.
   * - Editor open
     - Attach the view to the existing state; do not create a window-local copy.
   * - Editor close
     - Detach the view. The state remains available to other views and scoped
       resolution.
   * - Backing object removal
     - Unregister the state, or unregister its owned scope subtree.

An independently scoped child object may have its own ``ObjectState`` with a
``parent_state``. That relationship supplies ancestor context and optional
parent notification; it does not turn nested dataclass fields into recursive
states.

Saved and live baselines
------------------------

``parameters`` is the raw working copy. ``_live_resolved`` is the current
resolved view, including unsaved edits and inherited values.
``_saved_parameters`` and ``_saved_resolved`` are the last explicit baseline.

* ``update_parameter(path, value)`` mutates the flat working copy and
  invalidates the affected resolved values.
* ``mark_saved()`` reconstructs the backing object and advances the saved
  baseline.
* ``restore_saved()`` restores raw parameters from the saved baseline and
  recomputes resolution.
* ``dirty_fields`` compares the live and saved resolved views, while
  ``is_raw_dirty`` compares raw parameters with ``_saved_parameters``.

Do not normalize a lazy or inherited value by copying a constructor default
into the state. ``None`` may be the deliberate raw representation of an
inherited value; ObjectState's resolution and provenance are the authority.

Scoped context and notification
-------------------------------

``ObjectStateRegistry`` stores states by ``scope_id`` and supplies ancestor
objects for live or saved resolution. Register and unregister state objects at
their real lifecycle boundaries.

``forward_to_parent_state()`` is a notification bridge for independently
scoped child states. It emits the parent's resolved-change callbacks for an
explicit field path (or a scope-derived fallback). It neither mutates the
parent's parameters nor recursively saves or restores it.

Caller contract
---------------

1. Create and register a state with the backing object, not with a transient
   window.
2. Mutate through ``update_parameter()`` rather than editing ``parameters``
   directly.
3. Use ``mark_saved()`` and ``restore_saved()`` only for explicit saved/live
   workflows.
4. Use ``ObjectStateEditSession`` when a caller needs a generic update and
   reconstruction facade. The session delegates to the same state; it is not a
   parallel model.
5. Unregister the state when its backing object or owned scope is removed.
