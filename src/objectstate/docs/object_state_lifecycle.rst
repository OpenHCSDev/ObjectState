ObjectState Lifecycle and Contracts
===================================

Purpose
-------

ObjectState holds the UI MODEL extracted from an object without any UI framework dependencies. Form managers are the VIEW that reads/writes ObjectState; ObjectState persists beyond a single window.

Responsibilities
----------------

- Store parameters, types, defaults extracted by ``UnifiedParameterAnalyzer``
- Track user edits (``_user_set_fields``) and resets (``reset_fields``)
- Manage nested states (one ObjectState per nested dataclass field)
- Provide scoped discovery via ``ObjectStateRegistry`` for live context
- Provide saved baselines for save/cancel flows (``mark_saved`` / ``restore_saved``)

Lifecycle
---------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Owner
     - Creation/Destruction
   * - Parent containers
     - Create when child added; unregister when child removed
   * - Config windows
     - Create on window open; persist for lifetime of application
   * - Nested dataclasses
     - Created recursively inside parent ObjectState; inherit parent scope/context

Baseline and Cancel Behavior
----------------------------

.. note::
   ``saved_parameters`` is captured from the backing object (raw ``object.__getattribute__`` for dataclasses). If the backing object carries constructor defaults (e.g., lazy configs with class defaults), ``restore_saved()`` will reapply those concrete values unless the caller updates the baseline after normalization.

Key methods:

- ``mark_saved()``: capture current values (and resolved snapshot), clear dirty/reset flags. Call after successful save.
- ``restore_saved()``: revert ``parameters`` to ``saved_parameters`` and restore edit/reset flags. Call on cancel.
- ``is_dirty()``: true once a parameter is mutated after the last ``mark_saved()``.

Lazy Config Defaults
--------------------

- Lazy dataclasses created with constructor defaults may carry concrete values (e.g., ``StreamingConfig.port=5565``).
- If the backing object has not been explicitly set, normalize to ``None`` in ``ObjectState.parameters`` before opening the form, then call ``mark_saved()`` to update the baseline so cancel restores placeholders instead of class defaults.

Live Context Integration
------------------------

- ``ObjectStateRegistry`` stores all states keyed by ``scope_id``.
- ``ObjectStateRegistry.get_ancestor_objects(scope_id, use_saved=False)`` collects ancestor context by walking the scope hierarchy.
- Consumers use the ancestor objects to build context stacks for placeholder resolution.

Contracts for Callers
---------------------

1. Create/register ObjectState at lifecycle ownership points (object added, config window opened).
2. Pass ObjectState into form managers; do not mutate ``parameters`` directly from the UI—use dispatcher/state updates.
3. On save: call ``mark_saved()`` to capture the current state as the new baseline.
4. On cancel: call ``restore_saved()`` to revert to the last saved state.
5. When removing the owning object, unregister from ``ObjectStateRegistry`` to keep live context accurate.
