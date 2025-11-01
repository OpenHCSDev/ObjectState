Basic Usage
===========

This page provides basic examples of using lazy-config.

Simple Configuration
--------------------

The most basic usage of lazy-config:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import (
       set_base_config_type,
       LazyDataclassFactory,
       config_context,
   )

   @dataclass
   class AppConfig:
       api_key: str = "default-key"
       timeout: int = 30
       retries: int = 3

   # Setup
   set_base_config_type(AppConfig)
   factory = LazyDataclassFactory()
   LazyAppConfig = factory.make_lazy_simple(AppConfig)

   # Create configuration
   config = AppConfig(
       api_key="prod-key-123",
       timeout=60
   )

   # Use with context
   with config_context(config):
       lazy = LazyAppConfig()
       print(lazy.api_key)   # "prod-key-123"
       print(lazy.timeout)   # 60
       print(lazy.retries)   # 3 (default)

Multiple Configurations
-----------------------

Managing multiple configuration types:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class DatabaseConfig:
       host: str = "localhost"
       port: int = 5432
       database: str = "myapp"

   @dataclass
   class CacheConfig:
       backend: str = "redis"
       ttl: int = 300
       max_size: int = 1000

   # Create lazy versions
   factory = LazyDataclassFactory()
   LazyDB = factory.make_lazy_simple(DatabaseConfig)
   LazyCache = factory.make_lazy_simple(CacheConfig)

   # Setup configurations
   db_config = DatabaseConfig(
       host="prod.db.internal",
       port=5433,
       database="production"
   )

   cache_config = CacheConfig(
       backend="memcached",
       ttl=600
   )

   # Use both in context
   with config_context(db_config):
       with config_context(cache_config):
           db = LazyDB()
           cache = LazyCache()

           print(f"Connecting to {db.host}:{db.port}/{db.database}")
           print(f"Cache: {cache.backend}, TTL: {cache.ttl}s")

Function Integration
--------------------

Using lazy configs with functions:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class ProcessConfig:
       batch_size: int = 100
       parallel: bool = False
       log_level: str = "INFO"

   LazyProcess = LazyDataclassFactory().make_lazy_simple(ProcessConfig)

   def process_items(items: list, config: LazyProcess):
       """Process items using configuration."""
       print(f"Processing {len(items)} items")
       print(f"Batch size: {config.batch_size}")
       print(f"Parallel: {config.parallel}")
       print(f"Log level: {config.log_level}")

       # Process in batches
       for i in range(0, len(items), config.batch_size):
           batch = items[i:i + config.batch_size]
           print(f"Processing batch of {len(batch)} items")

   # Use it
   config = ProcessConfig(batch_size=50, parallel=True)

   with config_context(config):
       items = list(range(250))
       lazy_cfg = LazyProcess()
       process_items(items, lazy_cfg)

Overriding Values
-----------------

Explicitly override context values:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class ServerConfig:
       host: str = "0.0.0.0"
       port: int = 8000
       workers: int = 4

   LazyServer = LazyDataclassFactory().make_lazy_simple(ServerConfig)

   # Context provides defaults
   context_config = ServerConfig(
       host="prod.server.com",
       port=443,
       workers=8
   )

   with config_context(context_config):
       # Use all from context
       server1 = LazyServer()
       print(f"Server 1: {server1.host}:{server1.port}, workers={server1.workers}")
       # Output: Server 1: prod.server.com:443, workers=8

       # Override specific values
       server2 = LazyServer(port=8443)
       print(f"Server 2: {server2.host}:{server2.port}, workers={server2.workers}")
       # Output: Server 2: prod.server.com:8443, workers=8

       # Override multiple values
       server3 = LazyServer(host="localhost", port=8080, workers=1)
       print(f"Server 3: {server3.host}:{server3.port}, workers={server3.workers}")
       # Output: Server 3: localhost:8080, workers=1
