Context Management System
=========================

Configuration resolution requires tracking which configs are active at any point during execution. objectstate uses Python's ``contextvars`` for clean context stacking without frame introspection.

.. code-block:: python

   from objectstate import config_context

   with config_context(global_config):
       with config_context(app_config):
           # Both configs available for resolution
           lazy_instance.field_name  # Resolves through both contexts

The ``config_context()`` manager extracts dataclass fields and merges them into the context stack, enabling lazy resolution without explicit parameter passing.

Context Stacking
----------------

Contexts stack via ``contextvars.ContextVar``:

.. code-block:: python

   # objectstate/context_manager.py
   _config_context_base: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
       'config_context_base',
       default=None
   )

   # Track types pushed via config_context() for hierarchy queries
   context_type_stack: ContextVar[Tuple[Type, ...]] = ContextVar(
       'context_type_stack',
       default=()
   )

   @contextmanager
   def config_context(obj):
       """Stack a configuration context."""
       # Extract all dataclass fields from obj
       new_configs = extract_all_configs(obj)

       # Get current context
       current = _config_context_base.get()

       # Merge with current context
       merged = merge_configs(current, new_configs) if current else new_configs

       # Track type in stack for hierarchy queries
       current_types = context_type_stack.get()
       new_types = current_types + (type(obj),) if obj is not None else current_types

       # Set new context
       token = _config_context_base.set(merged)
       type_token = context_type_stack.set(new_types)
       try:
           yield
       finally:
           _config_context_base.reset(token)
           context_type_stack.reset(type_token)

Each ``with config_context()`` block adds configs to the stack. On exit, the context is automatically restored.

Context Type Stack
------------------

The ``context_type_stack`` ContextVar tracks which types have been pushed via ``config_context()``. This enables generic hierarchy queries without hardcoding type names:

.. code-block:: python

   from objectstate import get_context_type_stack

   with config_context(global_config):
       with config_context(app_config):
           with config_context(child_config):
               # Query the active type stack
               stack = get_context_type_stack()
               # Returns: (GlobalAppConfig, AppConfig, ChildConfig)

Hierarchy Registry
------------------

For cross-window updates (when parent config windows are open but not actively resolving),
the system maintains a persistent hierarchy registry:

.. code-block:: python

   # Registry maps child_type → parent_type
   _known_hierarchy: dict = {}

   def register_hierarchy_relationship(parent_type, child_type):
       """Register that parent_type is the parent of child_type in the config hierarchy."""
       parent_base = _normalize_type(parent_type)
       child_base = _normalize_type(child_type)
       if parent_base != child_base and not _is_global_type(parent_base):
           _known_hierarchy[child_base] = parent_base

   def unregister_hierarchy_relationship(child_type):
       """Remove hierarchy entry when form closes."""
       child_base = _normalize_type(child_type)
       _known_hierarchy.pop(child_base, None)

UI managers register their hierarchy when forms open:

.. code-block:: python

   # Child editor opens with context_obj=parent_config
   register_hierarchy_relationship(type(context_obj), type(object_instance))
   # Registers: ParentConfig → ChildConfig

This allows ``get_types_before_in_stack()`` to return correct ancestors even when
the parent window isn't actively inside a ``config_context()`` call.

Hierarchy Query Functions
-------------------------

The framework provides generic functions to query the hierarchy:

.. code-block:: python

   from objectstate import (
       get_types_before_in_stack,
       is_ancestor_in_context,
       is_same_type_in_context,
       get_ancestors_from_hierarchy
   )

   # Get all types that come before ChildConfig in the hierarchy
   ancestors = get_types_before_in_stack(ChildConfig)
   # Returns: [ParentConfig] (uses active stack or registry fallback)

   # Check if ParentConfig is an ancestor of ChildConfig
   is_ancestor = is_ancestor_in_context(ParentConfig, ChildConfig)
   # Returns: True

   # Check if two types are equivalent (handles lazy wrappers)
   is_same = is_same_type_in_context(LazyParentConfig, ParentConfig)
   # Returns: True

These functions first check the active ``context_type_stack``, then fall back to
the ``_known_hierarchy`` registry for cross-window scenarios.

Context Extraction
-----------------

The system extracts all dataclass fields from the provided object:

.. code-block:: python

   def extract_all_configs(context_obj) -> Dict[type, Any]:
       """Extract all dataclass configs from an object."""
       configs = {}
       
       # Extract dataclass fields
       if is_dataclass(context_obj):
           for field in fields(context_obj):
               value = getattr(context_obj, field.name)
               if is_dataclass(value):
                   # Store by the resolved nominal type
                   configs[type(value)] = value
       
       return configs

This flattens nested configs into a single dictionary keyed by nominal type.

Global Config Context
--------------------

Global config uses thread-local storage for stability:

.. code-block:: python

   # Thread-local storage for global config
   _global_config_storage: Dict[Type, threading.local] = {}
   
   def ensure_global_config_context(config_type: Type, config_instance: Any):
       """Store the instance as both the live and the saved global config of this thread."""
       set_global_config_for_editing(config_type, config_instance)

The global config is the base in thread-local storage; contextvars hold the layers
stacked on it. When a registered ``ObjectState`` holds the global config, that state
writes this storage on edit, save and restore (``docs/state_propagation.rst``, "The
state of the global config").

Resolution Integration
---------------------

The dual-axis resolver reads the layer stack of the active context:

.. code-block:: python

   from objectstate.dual_axis_resolver import resolve_with_provenance

   value, source_scope, source_type = resolve_with_provenance(LazyDatabaseConfig, "port")

Attribute access on a lazy config returns the ``value`` of this same result.

.. _precedence-order:

Precedence Order
~~~~~~~~~~~~~~~~

Resolution is class first. For each class in the MRO of the type being read, most specific
first, the resolver asks every layer from the innermost scope to the outermost for a config
of that class and returns the first value that is not ``None``, together with the layer's
scope id and the class it was read from. Only when no layer holds a value for a class is
the next, less specific class tried.

So the class decides before the scope does. Take ``Leaf(Base)``, a field ``value`` read on
``Leaf`` in a step, and two layers that hold a value:

==========================  ======================  =====================
Layer (scope)               ``Base.value``          ``Leaf.value``
==========================  ======================  =====================
plate (inner)               ``"base at plate"``     ``None``
global (outer)              ``None``                ``"leaf at global"``
==========================  ======================  =====================

The read returns ``"leaf at global"`` with source ``("", Leaf)``: ``Leaf`` is tried in
every scope before ``Base`` is tried in any, although the plate is the nearer scope. A
value on the same class in a nearer scope does win: with ``Leaf.value`` also set on the
plate, the plate's value is returned.

This is the only statement of the order. ``objectstate.dual_axis_resolver`` implements it
in ``_resolve_in_layers``; ``tests/test_resolution_precedence_order.py`` checks it for
every set of (class, scope) sites.

Usage Pattern
------------

.. code-block:: python

   from objectstate import config_context, ensure_global_config_context

   # Establish global context
   global_config = GlobalAppConfig(num_workers=4)
   ensure_global_config_context(GlobalAppConfig, global_config)

   # Create app config
   app_config = AppConfig(
       database_config=LazyDatabaseConfig(port=5433)
   )

   # Stack contexts
   with config_context(app_config):
       # Both global and app configs available
       # Lazy fields resolve through merged context
       result = process_with_config(app_config)

All lazy configs can resolve fields through both ``global_config`` and ``app_config`` contexts.

Context Cleanup
--------------

Contextvars automatically handle cleanup:

.. code-block:: python

   with config_context(pipeline_config):
       # Context active
       pass
   # Context automatically restored to previous state

No manual cleanup needed - Python's context manager protocol handles it.

Framework-Agnostic Context Stack Building
-----------------------------------------

``build_context_stack()`` is a context manager that enters the complete layer stack
that resolves one object, and leaves it again when the block ends. It is how an
``ObjectState`` resolves. The stack is built from the arguments and the global config
alone: a context the caller has entered is set aside for the duration of the block and
is active again after it. ``docs/state_propagation.rst`` ("What a resolved value is
computed from") states the rule this implements; plain attribute access on a lazy
object, everywhere else on this page, reads the entered context.

.. code-block:: python

   from objectstate import ObjectStateRegistry, build_context_stack

   ancestors = ObjectStateRegistry.get_ancestor_objects_with_scopes(scope_id)

   with build_context_stack(
       object_instance=current_object,
       ancestor_objects_with_scopes=ancestors,   # (scope_id, object), least specific first
       current_scope_id=scope_id,
   ):
       placeholder = resolve_placeholder(field_name)

Layers are entered outermost first:

1. **Global layer** - the global config, under scope ``""``
2. **Ancestors** - each under its own scope id
3. **Current object** - under ``current_scope_id``

Every layer carries a scope id, so ``resolve_with_provenance()`` can name the scope
that supplied a value. The global layer is the one ``config_context()`` puts below the
first layer entered while no context is active, which is always the case inside this
block. Nothing is set until the ``with`` block is entered. A layer that cannot be built
raises; the block never runs with a layer missing.
