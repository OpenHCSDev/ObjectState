Architectural Fixes & Improvements
===================================

This document describes critical architectural fixes applied to ObjectState to resolve
re-entrant cache invalidation issues and ensure robust state management.

Background
----------

ObjectState manages configuration state with lazy resolution, caching, and automatic delegate
synchronization. These features, while powerful, created architectural coupling that led to
re-entrant cache invalidation during save operations.

The Problem: Re-entrant Cache Invalidation
-------------------------------------------

When saving GlobalPipelineConfig, the following sequence would occur:

1. ``mark_saved()`` called on GlobalPipelineConfig (scope='')
2. Invalidation propagates to descendants (e.g., ``/home/ts/test_plate``)
3. Descendant calls ``_recompute_invalid_fields()`` to refresh its cache
4. During recomputation, ``get_ancestor_objects_with_scopes()`` is called
5. This attempts to get the current object via ``to_object()``
6. ``to_object()`` calls ``_check_and_sync_delegate()`` (delegate auto-detection)
7. Delegate sync calls ``invalidate_cache()``
8. **``_live_resolved`` is set to ``None`` while we're actively computing it**
9. Next ``.get()`` call crashes: ``'NoneType' object has no attribute 'get'``

This is a **re-entrant call problem** where a query operation (``to_object()``) has
hidden mutation side effects (delegate sync → cache invalidation).

Architectural Fixes Applied
----------------------------

Fix 1: Separate Query from Mutation in ``to_object()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem:** ``to_object()`` unconditionally called ``_check_and_sync_delegate()`` even
though it's conceptually a query operation.

**Solution:** Added ``sync_delegate`` parameter to control this behavior:

.. code-block:: python

    def to_object(self, *, update_delegate: bool = False, sync_delegate: bool = True):
        """Reconstruct object from flat parameters.

        Args:
            update_delegate: If True, apply reconstructed delegate to object_instance
            sync_delegate: If True (default), check for delegate changes before reconstruction.
                          Set to False during cache recomputation to avoid re-entrant invalidation.
        """
        if sync_delegate:
            self._check_and_sync_delegate()
        # ... rest of reconstruction

**Impact:**

- **Query purity**: Can now call ``to_object(sync_delegate=False)`` without side effects
- **Backward compatible**: Default behavior unchanged (``sync_delegate=True``)
- **Explicit control**: Delegate sync happens when you ask for it

Fix 2: Enable Real-Time MRO Inheritance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem:** During ``_recompute_invalid_fields()``, the code was using
``self.object_instance`` (original saved state) instead of reconstructing from current
parameters. This broke real-time MRO inheritance—editing ``WellFilterConfig.well_filter``
wouldn't update placeholders for inheriting fields like ``PathPlanningConfig.well_filter``.

**Solution:** Reconstruct current object from parameters without delegate sync:

.. code-block:: python

    # In _recompute_invalid_fields():

    # Get ancestors without triggering delegate sync
    ancestor_objects_with_scopes = ObjectStateRegistry.get_ancestor_objects_with_scopes(
        self.scope_id,
        skip_delegate_sync=True
    )

    # Reconstruct from CURRENT parameters for real-time inheritance
    current_obj = self.to_object(update_delegate=False, sync_delegate=False)

**Impact:**

- ✅ **Real-time inheritance**: Editing a base config field immediately updates all inheriting fields
- ✅ **No cache invalidation**: ``sync_delegate=False`` prevents re-entrant invalidation
- ✅ **Fresh values**: Objects reconstructed from current parameters, not stale saved state

Fix 3: ``skip_delegate_sync`` Parameter in ``get_ancestor_objects_with_scopes()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem:** This method was calling ``to_object()`` or ``saved_object`` on all ancestors,
triggering delegate sync even when just building a context stack.

**Solution:** Added ``skip_delegate_sync`` parameter:

.. code-block:: python

    @classmethod
    def get_ancestor_objects_with_scopes(
        cls,
        scope_id: Optional[str],
        use_saved: bool = False,
        skip_delegate_sync: bool = False
    ):
        """Get (scope_id, object) tuples from ancestors.

        Args:
            skip_delegate_sync: If True, skip delegate sync during object retrieval.
                               Use during cache recomputation to avoid re-entrant invalidation.
        """
        if use_saved:
            obj = state._extraction_target  # Direct access, no sync
        else:
            obj = state.to_object(update_delegate=False, sync_delegate=not skip_delegate_sync)

**Impact:**

- **Controlled side effects**: Caller decides whether delegate sync happens
- **Cache safety**: Can build context stacks without triggering invalidation
- **Performance**: Avoids unnecessary delegate checks during resolution

Fix 4: Descendant Saved Baseline Propagation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem:** When GlobalPipelineConfig was saved, descendant states (plates, steps) retained
their ``*`` dirty markers because their ``_saved_resolved`` wasn't updated to reflect the
new ancestor saved values.

**Solution:** After ``mark_saved()`` updates ``_saved_parameters``, propagate to descendants:

.. code-block:: python

    # In mark_saved():

    # After updating own saved_resolved, propagate to descendants
    changed_scope = ObjectStateRegistry._normalize_scope_id(self.scope_id)
    if changed_scope == "":
        # Global baseline change affects ALL other states
        descendant_scopes = [
            s.scope_id for s in ObjectStateRegistry._states.values()
            if ObjectStateRegistry._normalize_scope_id(s.scope_id) != ""
        ]
    else:
        prefix = changed_scope + "::"
        descendant_scopes = [
            s.scope_id for s in ObjectStateRegistry._states.values()
            if s.scope_id and ObjectStateRegistry._normalize_scope_id(s.scope_id).startswith(prefix)
        ]

    # Recompute each descendant's saved_resolved with new ancestor values
    for descendant_scope in descendant_scopes:
        state = ObjectStateRegistry._states.get(descendant_scope)
        if state:
            state._saved_resolved = state._compute_resolved_snapshot(use_saved=True)
            state._sync_materialized_state()  # Recalculate dirty fields

**Impact:**

- ✅ **Correct dirty detection**: Descendant dirty markers (``*``) clear when parent is saved
- ✅ **Cascade semantics**: Saving a parent propagates the saved baseline to all descendants
- ✅ **UI consistency**: Users see expected behavior when saving global config

Fix 5: Backward Compatibility for ``saved_parameters=None``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem:** Old snapshots/history could have ``saved_parameters=None`` or omit it entirely,
causing ``'NoneType' object has no attribute 'get'`` errors during restore or save.

**Solution:** Added defensive guards in multiple locations:

.. code-block:: python

    # In _compute_resolved_snapshot():
    if use_saved and self._saved_parameters is None:
        logger.warning(f"_saved_parameters is None for scope={self.scope_id}, using parameters as fallback")
        self._saved_parameters = copy.deepcopy(self.parameters)

    # In snapshot deserialization:
    saved_parameters=(
        state_data.get('saved_parameters')
        if state_data.get('saved_parameters') is not None
        else state_data['parameters']
    )

    # In history import:
    saved_parameters=(
        state_data.get('saved_parameters')
        if state_data.get('saved_parameters') is not None
        else state_data['parameters']
    )

**Impact:**

- ✅ **Robustness**: Handles legacy snapshots gracefully
- ✅ **No crashes**: Defensive guards prevent AttributeError
- ✅ **Automatic recovery**: Falls back to ``parameters`` when ``saved_parameters`` is missing

Architectural Principles
-------------------------

These fixes embody several key architectural principles:

**1. Separation of Concerns**

Query operations should not have mutation side effects. The ``sync_delegate`` parameter
separates the query (get current object) from the mutation (sync delegate).

**2. Explicit Over Implicit**

Delegate synchronization is now explicitly controlled via parameters rather than happening
automatically as a hidden side effect.

**3. Re-entrancy Safety**

Methods that call themselves (directly or indirectly) must guard against invalidating
state they're actively computing.

**4. Defensive Programming**

Handle edge cases (``None`` values, missing data) gracefully rather than crashing.

**5. Backward Compatibility**

New parameters default to preserving existing behavior. Existing code continues to work.

Testing & Validation
---------------------

These fixes were validated through:

1. **Manual testing**: Save GlobalPipelineConfig → no crash, descendants clear dirty markers
2. **Real-time inheritance**: Edit WellFilterConfig → inheriting fields update immediately
3. **Legacy compatibility**: Old snapshots with ``saved_parameters=None`` load correctly
4. **Multi-level inheritance**: Global → Pipeline → Step inheritance works correctly

Migration Guide
---------------

For library users, no migration is required. The changes are backward compatible.

For library developers extending ObjectState:

**If you call ``to_object()``:**

- Default behavior unchanged
- To avoid delegate sync during cache operations: ``to_object(sync_delegate=False)``

**If you call ``get_ancestor_objects_with_scopes()``:**

- Default behavior unchanged
- To avoid delegate sync during resolution: ``get_ancestor_objects_with_scopes(scope_id, skip_delegate_sync=True)``

Performance Impact
------------------

- **Positive**: Skipping delegate sync during cache recomputation reduces unnecessary checks
- **Neutral**: Default behavior unchanged for normal operations
- **Positive**: Context stack building is faster when ``skip_delegate_sync=True``

Future Improvements
-------------------

Potential future enhancements:

1. **Remove delegate auto-sync entirely**: Move to explicit sync-only at clear boundaries (save, load)
2. **Deferred invalidation**: Queue invalidations during cache computation rather than blocking them
3. **Immutable snapshots**: Make ``_live_resolved`` immutable during computation to catch bugs early

Summary
-------

These architectural fixes resolve a critical re-entrant cache invalidation issue while
maintaining backward compatibility and improving real-time MRO inheritance behavior.

**Key takeaway**: When designing stateful systems with caching and auto-sync features,
carefully separate query operations from mutations and guard against re-entrant calls
that invalidate state being actively computed.
