Quick Start Guide
==================

This guide will help you get started with lazy-config in minutes.

Installation
------------

Install lazy-config using pip:

.. code-block:: bash

   pip install lazy-config

Basic Setup
-----------

1. Define Your Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Start by defining your configuration as a regular Python dataclass:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass
   class GlobalConfig:
       output_dir: str = "/tmp"
       num_workers: int = 4
       debug: bool = False
       timeout: int = 30

2. Initialize the Framework
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set the base configuration type for your application:

.. code-block:: python

   from lazy_config import set_base_config_type

   set_base_config_type(GlobalConfig)

.. note::
   You only need to call ``set_base_config_type()`` once at application startup.

3. Create Lazy Version
~~~~~~~~~~~~~~~~~~~~~~~

Create a lazy version of your configuration:

.. code-block:: python

   from lazy_config import LazyDataclassFactory

   factory = LazyDataclassFactory()
   LazyGlobalConfig = factory.make_lazy_simple(GlobalConfig)

4. Use with Context
~~~~~~~~~~~~~~~~~~~

Use your configuration with context managers:

.. code-block:: python

   from lazy_config import config_context

   # Create concrete configuration
   global_cfg = GlobalConfig(
       output_dir="/data",
       num_workers=8,
       debug=True
   )

   # Use in context
   with config_context(global_cfg):
       lazy_cfg = LazyGlobalConfig()

       # Fields resolve from context
       print(lazy_cfg.output_dir)   # "/data"
       print(lazy_cfg.num_workers)  # 8
       print(lazy_cfg.debug)        # True
       print(lazy_cfg.timeout)      # 30 (from default)

Nested Contexts
---------------

One of the most powerful features is nested contexts:

.. code-block:: python

   from dataclasses import dataclass

   @dataclass
   class GlobalConfig:
       output_dir: str = "/tmp"
       num_workers: int = 4
       verbose: bool = False

   @dataclass
   class PipelineConfig:
       batch_size: int = 32
       learning_rate: float = 0.001

   @dataclass
   class StepConfig:
       input_size: int = 128
       output_size: int = 64

   # Create lazy versions
   LazyPipeline = LazyDataclassFactory().make_lazy_simple(PipelineConfig)
   LazyStep = LazyDataclassFactory().make_lazy_simple(StepConfig)

   # Use nested contexts
   global_cfg = GlobalConfig(output_dir="/data", num_workers=8)
   pipeline_cfg = PipelineConfig(batch_size=64)
   step_cfg = StepConfig(input_size=256)

   with config_context(global_cfg):
       with config_context(pipeline_cfg):
           with config_context(step_cfg):
               lazy_step = LazyStep()

               # Resolves from step context
               print(lazy_step.input_size)  # 256

               # Can also access pipeline context (if merged)
               lazy_pipeline = LazyPipeline()
               print(lazy_pipeline.batch_size)  # 64

Explicit Values Override Context
---------------------------------

You can always override context values explicitly:

.. code-block:: python

   global_cfg = GlobalConfig(output_dir="/data", num_workers=8)

   with config_context(global_cfg):
       # Override output_dir explicitly
       lazy_cfg = LazyGlobalConfig(output_dir="/custom")

       print(lazy_cfg.output_dir)   # "/custom" (explicit override)
       print(lazy_cfg.num_workers)  # 8 (from context)

Complete Example
----------------

Here's a complete example putting it all together:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import (
       set_base_config_type,
       LazyDataclassFactory,
       config_context,
   )

   # Step 1: Define configuration
   @dataclass
   class AppConfig:
       database_url: str = "sqlite:///app.db"
       cache_ttl: int = 300
       debug: bool = False
       max_connections: int = 10

   # Step 2: Initialize framework
   set_base_config_type(AppConfig)

   # Step 3: Create lazy version
   factory = LazyDataclassFactory()
   LazyAppConfig = factory.make_lazy_simple(AppConfig)

   # Step 4: Use in your application
   def process_data(data, config: LazyAppConfig):
       """Process data using configuration."""
       print(f"Using database: {config.database_url}")
       print(f"Cache TTL: {config.cache_ttl}")
       print(f"Debug mode: {config.debug}")
       return f"Processed {len(data)} items"

   # Step 5: Run with configuration
   def main():
       # Production configuration
       prod_config = AppConfig(
           database_url="postgresql://prod.db:5432/app",
           cache_ttl=600,
           debug=False,
           max_connections=50
       )

       with config_context(prod_config):
           data = ["item1", "item2", "item3"]
           lazy_cfg = LazyAppConfig()
           result = process_data(data, lazy_cfg)
           print(result)

   if __name__ == "__main__":
       main()

Next Steps
----------

* Learn about :doc:`architecture` and dual-axis inheritance
* Check out :doc:`examples/index` for more use cases
* Explore the :doc:`api/modules` for detailed documentation
