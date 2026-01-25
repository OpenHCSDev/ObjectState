Provenance Tracking
==================

Provenance tracking allows you to determine **which scope provided a resolved value** for inherited fields. This is particularly useful for debugging configuration inheritance and understanding where values originate in the dual-axis resolution system.

Overview
--------

When a field value is inherited from a parent context (global, pipeline, step, etc.), the provenance system tracks:

* **source_scope_id**: The scope identifier where the value was found (e.g., ``"plate_123::step_0"``)
* **source_type**: The type of the object that provided the value

This enables you to trace the origin of any inherited field value through the configuration hierarchy.

Key Concepts
------------

Provenance Information
~~~~~~~~~~~~~~~~~~~~~~

For each inherited field, provenance is stored as a tuple:

.. code-block:: python

    (source_scope_id, source_type)

* ``source_scope_id``: String identifier of the scope (e.g., ``""`` for global, ``"plate_123"`` for a plate, ``"plate_123::step_0"`` for a step)
* ``source_type``: The class type that provided the value

When a field has an **explicit value** (not inherited), it has **no provenance** - the value comes from the current object itself.

Live vs Saved Provenance
~~~~~~~~~~~~~~~~~~~~~~~~~

The provenance system maintains separate tracking for:

* **Live provenance**: Tracks where values come from in the current context (with all edits applied)
* **Saved provenance**: Captured at the last save point, representing the committed state

API Reference
-------------

ObjectState.get_provenance()
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get the source scope_id and type for an inherited field value:

.. code-block:: python

    from objectstate import ObjectStateRegistry

    # Get the ObjectState for your object
    state = ObjectStateRegistry.get_by_scope("plate_123::step_0")

    # Get provenance for a field
    provenance = state.get_provenance("well_filter")
    if provenance:
        source_scope, source_type = provenance
        print(f"well_filter comes from scope: {source_scope}")
        print(f"well_filter comes from type: {source_type.__name__}")
    else:
        print("well_filter is explicitly set on this object")

**Returns:**
* ``Tuple[str, type]`` if the value is inherited
* ``None`` if the value is explicitly set on the current object

**Note:** Returns provenance even when the resolved value is ``None`` (signature default). A "concrete None" just means the class default is ``None`` and nothing overrode it.

resolve_with_provenance()
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resolve a field value AND find its provenance source in ONE walk:

.. code-block:: python

    from objectstate.dual_axis_resolver import resolve_with_provenance

    # Resolve value and get provenance simultaneously
    value, source_scope, source_type = resolve_with_provenance(
        container_type=PathPlanningConfig,
        field_name="well_filter"
    )

    print(f"Value: {value}")
    print(f"From scope: {source_scope}")
    print(f"From type: {source_type.__name__}")

**Parameters:**

* ``container_type``: The type containing the field (e.g., ``LazyPathPlanningConfig``)
* ``field_name``: Name of the field to find provenance for (e.g., ``"well_filter"``)

**Returns:**

* ``value``: The resolved field value (may be ``None``)
* ``source_scope``: The scope_id where the value was found (or ``None``)
* ``source_type``: The type that provided the value (or ``None``)

**Performance:** Single walk instead of separate resolve + provenance calls.

get_field_provenance()
~~~~~~~~~~~~~~~~~~~~~~~

Convenience wrapper that returns only the scope and type (not the value):

.. code-block:: python

    from objectstate.dual_axis_resolver import get_field_provenance

    source_scope, source_type = get_field_provenance(
        container_type=PathPlanningConfig,
        field_name="well_filter"
    )

    print(f"Field comes from: {source_scope} ({source_type.__name__})")

**Note:** Calls ``resolve_with_provenance()`` internally and returns scope + type. Use ``resolve_with_provenance()`` directly when you also need the value.

Context Layer Stack
~~~~~~~~~~~~~~~~~~~

The provenance system uses the context layer stack for tracking:

.. code-block:: python

    from objectstate.context_manager import get_context_layer_stack

    # Get the current layer stack for provenance tracking
    layers = get_context_layer_stack()
    # Returns: [(scope_id, obj), ...] tuples

    # Used by get_field_provenance() to determine which scope provided a resolved value

The context layer stack tracks ``(scope_id, obj)`` tuples for provenance tracking, parallel to the merged config. It preserves hierarchy for inheritance source lookup.

Usage Examples
--------------

Debugging Inherited Values
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use provenance to understand where a value comes from:

.. code-block:: python

    from objectstate import ObjectStateRegistry

    state = ObjectStateRegistry.get_by_scope("plate_123::step_0")

    # Check where various fields come from
    for field_name in ["well_filter", "output_dir", "num_workers"]:
        provenance = state.get_provenance(field_name)
        if provenance:
            source_scope, source_type = provenance
            print(f"{field_name}: inherited from {source_scope} ({source_type.__name__})")
        else:
            print(f"{field_name}: explicitly set on this object")

Example output:

.. code-block:: text

    well_filter: inherited from  (GlobalPipelineConfig)
    output_dir: inherited from plate_123 (PlateConfig)
    num_workers: explicitly set on this object

Tracing Value Origins
~~~~~~~~~~~~~~~~~~~~~~

Trace the full inheritance chain for a field:

.. code-block:: python

    from objectstate.dual_axis_resolver import resolve_with_provenance

    def trace_field_origin(container_type, field_name):
        """Trace where a field value comes from."""
        value, source_scope, source_type = resolve_with_provenance(
            container_type, field_name
        )

        print(f"\nField: {field_name}")
        print(f"  Value: {value}")
        print(f"  Source scope: {source_scope or '<none>'}")
        print(f"  Source type: {source_type.__name__ if source_type else '<none>'}")

        if source_scope == "":
            print("  → Value comes from global configuration")
        elif source_scope:
            print(f"  → Value inherited from scope: {source_scope}")
        else:
            print("  → Value is a class default (no override)")

    # Use it
    trace_field_origin(PathPlanningConfig, "well_filter")
    trace_field_origin(PathPlanningConfig, "output_dir_suffix")

UI Integration
~~~~~~~~~~~~~~

Provenance information can be displayed in UI elements to help users understand where values come from:

.. code-block:: python

    from objectstate import ObjectStateRegistry

    state = ObjectStateRegistry.get_by_scope("plate_123::step_0")

    def get_field_display_info(field_name):
        """Get display information for a field including provenance."""
        value = getattr(state.object_instance, field_name, None)
        provenance = state.get_provenance(field_name)

        if provenance:
            source_scope, source_type = provenance
            origin = f"Inherited from {source_type.__name__}"
            if source_scope:
                origin += f" ({source_scope})"
        else:
            origin = "Explicitly set"

        return {
            "value": value,
            "origin": origin
        }

    # Display in UI
    info = get_field_display_info("well_filter")
    print(f"well_filter: {info['value']} [{info['origin']}]")

Provenance in Snapshots
-------------------------

Provenance is captured in state snapshots for history tracking:

.. code-block:: python

    from objectstate import ObjectStateRegistry

    # Provenance is stored in the snapshot
    state = ObjectStateRegistry.get_by_scope("plate_123::step_0")

    # The _live_provenance dict tracks provenance for all inherited fields
    # Format: {field_name: (scope_id, source_type)}
    for field_name, (scope_id, source_type) in state._live_provenance.items():
        print(f"{field_name}: from {scope_id} ({source_type.__name__})")

When recording snapshots for undo/redo, the provenance information is preserved, allowing you to trace the origin of values at any point in history.

Best Practices
--------------

1. **Use provenance for debugging**: When unexpected values appear, use ``get_provenance()`` to trace their origin.

2. **Check for explicit vs inherited**: ``None`` return from ``get_provenance()`` means the value is explicitly set, not inherited.

3. **Combine with value inspection**: Use ``resolve_with_provenance()`` when you need both the value and its origin in a single call.

4. **UI feedback**: Display provenance information in tooltips or status text to help users understand configuration inheritance.

5. **History analysis**: Use provenance in snapshots to understand how values evolved over time.

Implementation Details
----------------------

How Provenance Works
~~~~~~~~~~~~~~~~~~~~

The provenance system works through these mechanisms:

1. **Context Layer Stack**: The ``config_context()`` manager tracks ``(scope_id, obj)`` tuples as contexts are pushed.

2. **Dual-Axis Resolution with Provenance**: When resolving inherited fields, ``resolve_with_provenance()`` walks both the MRO and context hierarchy, returning the first concrete value found along with its source information.

3. **Live Provenance Cache**: ``ObjectState`` maintains ``_live_provenance`` dict that stores ``(scope_id, source_type)`` tuples for each inherited field.

4. **Snapshot Integration**: Provenance is included in ``StateSnapshot`` objects for history tracking.

Performance Considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Provenance tracking adds minimal overhead - it's computed during the same resolution walk that finds values.
* Use ``resolve_with_provenance()`` for combined value+provenance lookup instead of separate calls.
* The ``_live_provenance`` cache is invalidated when contexts change, ensuring accurate tracking.

See Also
--------

* :doc:`architecture` - Dual-axis resolution system
* :doc:`state_management` - ObjectState and state snapshots
* :doc:`context_system` - Context management and stacking
