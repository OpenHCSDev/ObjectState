State Propagation and Parent Notification
=========================================

ObjectState provides mechanisms for propagating state changes from child states to parent states, enabling hierarchical UI updates and cross-component notifications.

Overview
--------

In complex UI hierarchies with nested ObjectState instances (e.g., a step state containing function states), changes in child states often need to notify parent states. The state propagation system provides:

- **Parent notification**: Child states can forward changes to parents
- **Reentrancy protection**: Prevents infinite loops during propagation
- **Automatic field detection**: Infers the parent field from scope hierarchy
- **Callback triggering**: Fires parent on_resolved_changed callbacks

Use Cases
---------

Function Parameter Changes
~~~~~~~~~~~~~~~~~~~~~~~~~~

When function parameters change in a function pane, the parent step needs to know to update its list item preview:

.. code-block:: python

   # Function pane state is child of step state
   # When function parameters change:
   func_state.forward_to_parent_state('func')
   # Step state's on_resolved_changed callbacks fire
   # List item preview updates automatically

Nested Dataclass Updates
~~~~~~~~~~~~~~~~~~~~~~~~

When a nested dataclass field changes, the parent may need to react:

.. code-block:: python

   # processing_config is a nested dataclass
   processing_state.forward_to_parent_state('processing_config')
   # Parent knows processing_config conceptually changed

Cross-Component Synchronization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Multiple widgets viewing the same hierarchical data stay synchronized:

.. code-block:: python

   # Parent widget shows summary
   # Child widget shows details
   # When details change, summary updates via parent notification

Architecture
------------

forward_to_parent_state Method
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The primary API for parent notification:

.. code-block:: python

   def forward_to_parent_state(self, field_path: Optional[str] = None) -> None:
       """Forward child state changes to parent state.
       
       Notifies the parent state that a field has conceptually changed,
       causing the parent's on_resolved_changed callbacks to fire.
       
       Args:
           field_path: Dotted path of field that changed. If None, auto-detects.
       
       Raises:
           RuntimeError: If state has no parent state.
       """

Key Behaviors
~~~~~~~~~~~~~

**Reentrancy Guard**:

.. code-block:: python

   # Prevents infinite loops during propagation
   if getattr(self, '_forwarding_to_parent', False):
       return
   self._forwarding_to_parent = True
   try:
       # ... forward logic ...
   finally:
       self._forwarding_to_parent = False

**Auto-Detection**:

.. code-block:: python

   # If field_path not provided, detect from scope_id
   # Example: scope_id "plate::step_0::function_1"
   # Extracts: "function" (removes numeric suffix)
   parts = self.scope_id.split('::')
   last = parts[-1]
   m = re.match(r'^(.+?)_\\d+$', last)
   parent_field = m.group(1) if m else last

**Callback Execution**:

Fires all parent on_resolved_changed callbacks with the changed field.

Usage Examples
--------------

Basic Parent Notification
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from objectstate import ObjectState
   
   # Create parent and child states
   parent_state = ObjectState(
       scope_id="parent",
       parameters=['field_a', 'field_b']
   )
   child_state = ObjectState(
       scope_id="parent::child_0",
       parameters=['detail_x', 'detail_y'],
       parent_state=parent_state,
       parent_field_name='child_field'
   )
   
   # Register callback on parent
   def on_parent_changed(changed_paths):
       print(f"Parent field changed: {changed_paths}")
   
   parent_state.on_resolved_changed(on_parent_changed)
   
   # In child, trigger parent notification
   child_state.forward_to_parent_state('child_field')
   # Output: "Parent field changed: {'child_field'}"

Function Pane Integration
~~~~~~~~~~~~~~~~~~~~~~~~~

Real-world example from function pane widgets:

.. code-block:: python

   # In FunctionPaneWidget.create_parameter_form()
   func_state = ObjectState(
       scope_id=f"{step_scope}::function_{index}",
       parameters=['enabled', 'param1', 'param2'],
       parent_state=step_state,
       parent_field_name='func'
   )
   
   # Forward changes to parent for UI flash
   def forward_to_step(changed_paths):
       func_state.forward_to_parent_state('func')
   
   func_state.on_resolved_changed(forward_to_step)

API Reference
-------------

.. py:method:: ObjectState.forward_to_parent_state(field_path=None)

   Forward child state changes to parent state.
   
   :param field_path: Dotted path of field that changed. If None, auto-detects
                     from scope_id by extracting the last segment and removing
                     numeric suffixes (e.g., "function_0" becomes "function").
   :type field_path: str or None
   :raises RuntimeError: If state has no parent state
   
   Example:
   
   .. code-block:: python
   
      # With explicit field path
      child_state.forward_to_parent_state('processing_config')
      
      # With auto-detection (scope_id="parent::child_0" -> field="child")
      child_state.forward_to_parent_state()

Best Practices
--------------

When to Use
~~~~~~~~~~~

Use forward_to_parent_state when:

1. Child state represents a field of parent (e.g., function in step)
2. Parent UI needs to update when child changes (e.g., list item preview)
3. Cross-component synchronization is needed
4. Hierarchical state changes should propagate upward

Field Path Selection
~~~~~~~~~~~~~~~~~~~~

- **Explicit path**: Use when field name differs from scope suffix
- **Auto-detect**: Let system infer from scope_id for consistency
- **Dotted paths**: Use for deep nesting (e.g., "config.subconfig.field")

Performance Considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~

- Forwarding is synchronous and lightweight
- Reentrancy guard prevents exponential callback chains
- Only fires parent callbacks, not grandparent (by design)
- Use sparingly to avoid excessive parent updates
