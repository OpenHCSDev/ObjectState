Architecture
============

Understanding the architecture of objectstate helps you leverage its full power.

For state lifecycles and the registry, see :doc:`state_management`.

Dual-Axis Resolution
---------------------

The framework uses pure MRO-based dual-axis resolution.

X-Axis (Context Hierarchy)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Contexts are traversed from most specific to least specific::

   Step Context → Pipeline Context → Global Context → Static Defaults

**Example:**

.. code-block:: python

   @dataclass
   class GlobalConfig:
       value: str = "global"

   @dataclass
   class PipelineConfig:
       value: str = "pipeline"

   @dataclass
   class StepConfig:
       value: str = None  # Will inherit

   with config_context(global_cfg):        # X-axis level 3
       with config_context(pipeline_cfg):  # X-axis level 2
           with config_context(step_cfg):  # X-axis level 1
               lazy = LazyStepConfig()
               # Resolves: step → pipeline → global → defaults
               print(lazy.value)  # "pipeline" (from PipelineConfig)

Y-Axis (MRO Traversal)
~~~~~~~~~~~~~~~~~~~~~~

Within the same context, inheritance follows Python's Method Resolution Order (MRO)::

   Most specific class → Least specific class (following Python's MRO)

**Example:**

.. code-block:: python

   @dataclass
   class BaseConfig:
       base_field: str = "base"

   @dataclass
   class MiddleConfig(BaseConfig):
       middle_field: str = "middle"

   @dataclass
   class ChildConfig(MiddleConfig):
       child_field: str = "child"

   # MRO: ChildConfig → MiddleConfig → BaseConfig
   lazy = LazyChildConfig()
   # Can access all fields through MRO

How It Works
------------

1. Context Flattening
~~~~~~~~~~~~~~~~~~~~~

The context hierarchy is flattened into a single ``available_configs`` dict:

.. code-block:: text

   {
       "GlobalConfig": <global_config_instance>,
       "PipelineConfig": <pipeline_config_instance>,
       "StepConfig": <step_config_instance>
   }

2. Field Resolution
~~~~~~~~~~~~~~~~~~~

For each field resolution, the framework:

1. **Traverses the requesting object's MRO** from most to least specific
2. **For each MRO class**, checks if there's a config instance in ``available_configs`` with a concrete (non-None) value
3. **Returns the first concrete value found**

3. Resolution Flow
~~~~~~~~~~~~~~~~~~

.. code-block:: text

   ┌─────────────────────────────────────────┐
   │ Field Access: objectstate.some_field    │
   └────────────────┬────────────────────────┘
                    │
                    ▼
   ┌─────────────────────────────────────────┐
   │ Stage 1: Check instance value           │
   │ If value is not None → return value     │
   └────────────────┬────────────────────────┘
                    │
                    ▼
   ┌─────────────────────────────────────────┐
   │ Stage 2: Simple field path lookup       │
   │ Check current context for field         │
   └────────────────┬────────────────────────┘
                    │
                    ▼
   ┌─────────────────────────────────────────┐
   │ Stage 3: Inheritance resolution         │
   │ Traverse MRO × Context hierarchy        │
   │ Return first concrete value             │
   └────────────────┬────────────────────────┘
                    │
                    ▼
   ┌─────────────────────────────────────────┐
   │ Return resolved value or None           │
   └─────────────────────────────────────────┘

Context Management
------------------

The framework uses Python's ``contextvars`` for thread-safe context management:

.. code-block:: python

   from contextvars import ContextVar

   current_temp_global: ContextVar = ContextVar('current_temp_global')

Benefits
~~~~~~~~

* **Thread-safe**: Each thread has its own context
* **Async-compatible**: Works with async/await
* **Clean scoping**: Contexts are automatically cleaned up
* **No global state pollution**: Isolated per-execution context

Lazy Resolution
---------------

When Fields Resolve
~~~~~~~~~~~~~~~~~~~

Fields are resolved lazily when accessed:

.. code-block:: python

   with config_context(config):
       lazy = LazyConfig()
       # No resolution yet

       value = lazy.field_name
       # Resolution happens HERE

Projecting raw state to the base dataclass
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``to_base_config()`` converts a lazy configuration to its authored base type
without resolving raw ``None`` inheritance markers. This operation is used while
building a context, when resolving too early would consult an incomplete or
stale hierarchy:

.. code-block:: python

   with config_context(config):
       lazy = LazyConfig()
       concrete = lazy.to_base_config()
       # Raw inheritance markers remain available to context resolution.

Use ``resolve_lazy_configurations_for_serialization()`` inside an established
``config_context`` when a boundary instead needs recursively resolved concrete
values for serialization.

Concrete-to-lazy projection and composition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every generated lazy type exposes ``from_config()``. With one concrete instance,
it projects constructor fields into the matching lazy type. Passing an
``inherited`` concrete instance makes the result sparse: values equal to the
inherited instance are omitted and therefore continue to inherit.

For a generated aggregate lazy configuration, ``from_config()`` also composes
multiple concrete registered configuration values. The base-to-lazy registry
determines each aggregate field; callers do not supply a field-name map. An
unregistered concrete type, a duplicate value for one aggregate field, a value
whose mapped field is absent, or any lazy input fails explicitly.

Default preservation
~~~~~~~~~~~~~~~~~~~~

Lazy scalar fields store raw ``None`` so inheritance remains observable. When a
base field had a concrete default or default factory, the generated field keeps
it in ``_inherited_default`` / ``_inherited_default_factory`` metadata. A lazy
read uses that metadata only as the standalone fallback after context and MRO
resolution cannot provide a value. The default is not copied into the raw field.

Nested dataclass fields reuse the lazy type already registered for their authored
base. The factory creates and registers a nested lazy type only when no mapping
exists, then uses that nominal type as the field's default factory. At import
time ObjectState also registers its lazy-to-base lookup with
``python_introspect.register_type_resolver()``, so documentation and parameter
analysis recover the authored dataclass rather than inspecting generated proxy
fields.

Dataclass Reconstruction Hook
-----------------------------

ObjectState sometimes needs to reconstruct dataclass instances from their resolved field values
(for example in :py:func:`objectstate.lazy_factory.resolve_lazy_configurations_for_serialization`).

By default, ObjectState rebuilds a dataclass as::

   type(obj)(**resolved_fields)

If your dataclass uses a custom constructor (common when using ``@dataclass(init=False)``),
the default reconstruction may fail because the constructor does not accept the dataclass field
names as keyword arguments.

To support this cleanly, a dataclass may define a rebuild hook:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass(frozen=True, init=False)
   class MySpec:
       outputs: tuple[object, ...]
       primary: int

       def __init__(self, *outputs: object, primary: int = 0):
           object.__setattr__(self, "outputs", tuple(outputs))
           object.__setattr__(self, "primary", primary)

       @classmethod
       def __objectstate_rebuild__(cls, **fields):
           # fields is the resolved dataclass field mapping
           return cls(*fields["outputs"], primary=fields.get("primary", 0))

When present, ObjectState will call ``__objectstate_rebuild__(**resolved_fields)`` instead of
calling ``cls(**resolved_fields)``.

Type System
-----------

Lazy Type Registry
~~~~~~~~~~~~~~~~~~

The framework maintains bidirectional mappings between generated lazy types and
their authored base types. These registries are also the authority used by
``from_config()`` composition and nested lazy reuse:

.. code-block:: python

   _lazy_type_registry: Dict[Type, Type] = {
       LazyGlobalConfig: GlobalConfig,
       LazyPipelineConfig: PipelineConfig,
       # ...
   }

Type Safety
~~~~~~~~~~~

All lazy dataclasses maintain type annotations from their base classes:

.. code-block:: python

   @dataclass
   class MyConfig:
       value: str = "default"
       count: int = 0

   LazyMyConfig = factory.make_lazy_simple(MyConfig)

   # Type checkers understand LazyMyConfig fields
   lazy: LazyMyConfig = LazyMyConfig()
   reveal_type(lazy.value)  # str
   reveal_type(lazy.count)  # int

Performance Considerations
--------------------------

Memory
~~~~~~

* Lazy configs store only explicitly set fields
* Context merging creates new merged config objects
* Nested contexts create a chain of merged configs

CPU
~~~

* Field resolution has O(MRO depth × Context depth) complexity
* In practice, this is very fast (typically < 10 classes in MRO, < 5 contexts)
* Use cache warming for performance-critical paths

Best Practices
~~~~~~~~~~~~~~

1. **Minimize context depth**: Typically 2-3 levels (global, pipeline, step)
2. **Use cache warming**: Pre-warm for frequently accessed configs
3. **Materialize when needed**: Convert to base config after resolution for repeated access
4. **Avoid deep inheritance**: Keep MRO shallow for better performance

Decorator Pattern and Field Injection
--------------------------------------

When using ``auto_create_decorator``, the framework provides automatic field injection and lazy class generation.

How auto_create_decorator Works
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from objectstate import auto_create_decorator
   from dataclasses import dataclass

   # Apply to a global config class
   @auto_create_decorator
   @dataclass
   class GlobalPipelineConfig:
       num_workers: int = 1
       output_dir: str = "/tmp"

   # This automatically creates:
   # 1. A decorator named `global_pipeline_config`
   # 2. A lazy class named `PipelineConfig`

The decorator name is derived from the class name:

* Remove "Global" prefix: ``GlobalPipelineConfig`` → ``PipelineConfig``
* Convert to snake_case: ``PipelineConfig`` → ``global_pipeline_config``

Field Injection Mechanism
~~~~~~~~~~~~~~~~~~~~~~~~~~

When you use the generated decorator, the decorated class is automatically injected as a field into the global config:

.. code-block:: python

   @global_pipeline_config
   @dataclass
   class WellFilterConfig:
       well_filter: str = None
       mode: str = "include"

   # After module loading, GlobalPipelineConfig has:
   # - well_filter_config: WellFilterConfig = WellFilterConfig()
   # And LazyWellFilterConfig is auto-created

**Injection process:**

1. Decorated classes are registered for injection
2. At module load completion, ``_inject_all_pending_fields()`` is called
3. Field name is snake_case of class name (``WellFilterConfig`` → ``well_filter_config``)
4. Lazy version is created (``LazyWellFilterConfig``)
5. Both the field and lazy class are added to the global config

**Benefits:**

* Modular configuration structure
* Each component's config is automatically part of global config
* No manual field registration required
* Type-safe with full IDE support

Decorator Parameters
~~~~~~~~~~~~~~~~~~~~

The generated decorator supports optional parameters to control behavior.

inherit_as_none Parameter
^^^^^^^^^^^^^^^^^^^^^^^^^^

Sets all inherited fields from parent classes to ``None`` by default:

.. code-block:: python

   @dataclass
   class StepWellFilterConfig:
       persistent: bool = True
       well_filter: str = None

   @dataclass
   class StreamingDefaults:
       host: str = "localhost"
       port: int = 5000

   @global_pipeline_config(inherit_as_none=True)  # Default
   @dataclass
   class StreamingConfig(StepWellFilterConfig, StreamingDefaults):
       """Uses multiple inheritance.

       All inherited fields (persistent, well_filter, host, port)
       are automatically set to None for proper lazy resolution.
       """
       stream_type: str = "napari"

**Why this matters:**

* Enables proper dual-axis inheritance with multiple inheritance
* Allows polymorphic access without type-specific attribute names
* Only explicitly defined fields keep their concrete defaults
* Uses ``InheritAsNoneMeta`` metaclass internally
* Critical for complex inheritance hierarchies

ui_hidden Parameter
^^^^^^^^^^^^^^^^^^^

Hides configs from UI while maintaining decorator behavior:

.. code-block:: python

   @global_pipeline_config(ui_hidden=True)
   @dataclass
   class NapariDisplayConfig:
       display_mode: str = "2D"
       colormap: str = "gray"
       # Hidden from UI but available for inheritance

**Effects:**

* Sets ``_ui_hidden = True`` on both base and lazy class
* Config remains in context for lazy resolution
* Decorator still creates lazy version and injects field
* UI layer checks ``_ui_hidden`` to skip rendering

**Use cases:**

* Intermediate configs only inherited by other configs
* Internal implementation details
* Base classes not meant for direct instantiation

Automatic Nested Dataclass Lazification
----------------------------------------

The framework automatically converts nested dataclass fields to their lazy versions.

How It Works
~~~~~~~~~~~~

.. code-block:: python

   from dataclasses import dataclass
   from objectstate import LazyDataclassFactory

   @dataclass
   class PathPlanningConfig:
       output_dir_suffix: str = "_processed"
       sub_dir: str = "images"

   @dataclass
   class GlobalPipelineConfig:
       num_workers: int = 1
       path_planning_config: PathPlanningConfig = PathPlanningConfig()

   # Create lazy version
   LazyPipelineConfig = LazyDataclassFactory.make_lazy_simple(
       GlobalPipelineConfig
   )

   # The path_planning_config field is automatically converted to
   # LazyPathPlanningConfig - no manual creation needed!

**Process:**

1. Framework detects nested dataclass fields
2. Automatically creates lazy version of nested type
3. Registers type mapping via ``register_lazy_type_mapping()``
4. Preserves field metadata (e.g., ``ui_hidden`` flag)
5. Creates default factories for Optional dataclass fields

**Benefits:**

* No need to manually create lazy versions first
* Recursive lazification of deeply nested configs
* Automatic type mapping registration
* Preserves all field properties and metadata

Global Configuration Context
-----------------------------

Understanding set_base_config_type vs ensure_global_config_context
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The framework provides two related but distinct functions:

**set_base_config_type(config_type: Type)**

Sets the **type** (class) for the framework:

.. code-block:: python

   from objectstate import set_base_config_type

   set_base_config_type(GlobalPipelineConfig)

* Call once at application startup
* Registers the base config type for the framework
* Required for type validation and registry
* Does not set any concrete values

**ensure_global_config_context(config_type: Type, instance: Any)**

Sets the **instance** (concrete values) for resolution:

.. code-block:: python

   from objectstate import ensure_global_config_context

   global_config = GlobalPipelineConfig(
       num_workers=8,
       output_dir="/data"
   )

   ensure_global_config_context(GlobalPipelineConfig, global_config)

* Call after creating global config instance
* Uses thread-local storage for thread safety
* Required for lazy resolution to work
* Internally calls ``set_global_config_for_editing()``
* Should be called at application startup (GUI) or before pipeline execution

**Key Differences:**

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Aspect
     - set_base_config_type
     - ensure_global_config_context
   * - What it sets
     - Type (class)
     - Instance (concrete values)
   * - When to call
     - Once at startup
     - After creating instance
   * - Purpose
     - Type registration
     - Enable lazy resolution
   * - Thread safety
     - Global registry
     - Thread-local storage

Thread Safety
-------------

The framework is fully thread-safe through:

1. **Thread-local storage** for global configs
2. **ContextVars** for temporary contexts
3. **Immutable frozen dataclasses** (when using ``frozen=True``)

This makes it safe to use in multi-threaded applications, including web servers and async applications.
