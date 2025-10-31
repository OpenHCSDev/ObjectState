Architecture
============

Understanding the architecture of lazy-config helps you leverage its full power.

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

.. code-block:: python

   {
       'GlobalConfig': <global_config_instance>,
       'PipelineConfig': <pipeline_config_instance>,
       'StepConfig': <step_config_instance>
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
   │ Field Access: lazy_config.some_field    │
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

Caching Behavior
~~~~~~~~~~~~~~~~

Currently, fields are resolved on each access. For performance-critical applications, you can:

1. **Pre-warm caches:**

   .. code-block:: python

      from lazy_config import prewarm_config_analysis_cache
      prewarm_config_analysis_cache([Config1, Config2, Config3])

2. **Convert to base config** once resolved:

   .. code-block:: python

      with config_context(config):
          lazy = LazyConfig()
          concrete = lazy.to_base_config()
          # concrete now has all values materialized

Type System
-----------

Lazy Type Registry
~~~~~~~~~~~~~~~~~~

The framework maintains a registry mapping lazy types to base types:

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

Thread Safety
-------------

The framework is fully thread-safe through:

1. **Thread-local storage** for global configs
2. **ContextVars** for temporary contexts
3. **Immutable frozen dataclasses** (when using ``frozen=True``)

This makes it safe to use in multi-threaded applications, including web servers and async applications.
