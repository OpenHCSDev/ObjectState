Dual-Axis Inheritance
=====================

Examples demonstrating the dual-axis inheritance system.

Understanding Dual-Axis Inheritance
------------------------------------

Lazy-config uses two axes for configuration resolution:

* **X-Axis**: Context hierarchy (Global → Pipeline → Step)
* **Y-Axis**: Class inheritance (MRO-based)

X-Axis: Context Hierarchy
--------------------------

Context hierarchy allows nested contexts to override outer contexts:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class GlobalConfig:
       environment: str = "dev"
       log_level: str = "INFO"
       timeout: int = 30

   @dataclass
   class PipelineConfig:
       pipeline_name: str = "default"
       timeout: int = 60  # Override global timeout

   @dataclass
   class StepConfig:
       step_name: str = "process"
       timeout: int = 10  # Override again for this step

   # Create lazy versions
   factory = LazyDataclassFactory()
   LazyGlobal = factory.make_lazy_simple(GlobalConfig)
   LazyPipeline = factory.make_lazy_simple(PipelineConfig)
   LazyStep = factory.make_lazy_simple(StepConfig)

   # Setup configs
   global_cfg = GlobalConfig(
       environment="production",
       log_level="WARNING",
       timeout=30
   )

   pipeline_cfg = PipelineConfig(
       pipeline_name="data-processing",
       timeout=60
   )

   step_cfg = StepConfig(
       step_name="transform",
       timeout=10
   )

   # Nested contexts demonstrate X-axis resolution
   with config_context(global_cfg):
       lazy_global = LazyGlobal()
       print(f"Global timeout: {lazy_global.timeout}")  # 30

       with config_context(pipeline_cfg):
           lazy_pipeline = LazyPipeline()
           print(f"Pipeline timeout: {lazy_pipeline.timeout}")  # 60 (overrides global)

           with config_context(step_cfg):
               lazy_step = LazyStep()
               print(f"Step timeout: {lazy_step.timeout}")  # 10 (overrides pipeline)

Y-Axis: Class Inheritance
--------------------------

Class inheritance allows child classes to inherit and override parent fields:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class BaseProcessConfig:
       """Base configuration for all processes."""
       input_dir: str = "/data/input"
       output_dir: str = "/data/output"
       format: str = "json"

   @dataclass
   class DataProcessConfig(BaseProcessConfig):
       """Configuration for data processing."""
       batch_size: int = 100
       parallel: bool = False

   @dataclass
   class MLProcessConfig(DataProcessConfig):
       """Configuration for ML processing."""
       model_path: str = "/models/default"
       use_gpu: bool = False

   # Create lazy version of the most specific class
   LazyML = LazyDataclassFactory().make_lazy_simple(MLProcessConfig)

   # Set up configuration
   ml_config = MLProcessConfig(
       input_dir="/data/ml/input",     # From BaseProcessConfig
       output_dir="/data/ml/output",   # From BaseProcessConfig
       format="parquet",               # From BaseProcessConfig
       batch_size=500,                 # From DataProcessConfig
       parallel=True,                  # From DataProcessConfig
       model_path="/models/bert",      # From MLProcessConfig
       use_gpu=True                    # From MLProcessConfig
   )

   with config_context(ml_config):
       lazy = LazyML()

       # All fields accessible through MRO
       print(f"Input: {lazy.input_dir}")      # BaseProcessConfig
       print(f"Output: {lazy.output_dir}")    # BaseProcessConfig
       print(f"Format: {lazy.format}")        # BaseProcessConfig
       print(f"Batch: {lazy.batch_size}")     # DataProcessConfig
       print(f"Parallel: {lazy.parallel}")    # DataProcessConfig
       print(f"Model: {lazy.model_path}")     # MLProcessConfig
       print(f"GPU: {lazy.use_gpu}")          # MLProcessConfig

Selective Inheritance
---------------------

Using None to enable inheritance from parent contexts:

.. code-block:: python

   from dataclasses import dataclass
   from lazy_config import LazyDataclassFactory, config_context

   @dataclass
   class GlobalConfig:
       database_url: str = "postgresql://global"
       cache_enabled: bool = True
       timeout: int = 30

   @dataclass
   class ServiceConfig:
       service_name: str = "my-service"
       database_url: str = None  # Will inherit from GlobalConfig
       cache_enabled: bool = None  # Will inherit from GlobalConfig
       timeout: int = 5  # Override global timeout

   # Create lazy versions
   factory = LazyDataclassFactory()
   LazyGlobal = factory.make_lazy_simple(GlobalConfig)
   LazyService = factory.make_lazy_simple(ServiceConfig)

   # Setup
   global_cfg = GlobalConfig(
       database_url="postgresql://prod.db:5432/app",
       cache_enabled=True,
       timeout=30
   )

   service_cfg = ServiceConfig(
       service_name="payment-service",
       # database_url is None - will inherit
       # cache_enabled is None - will inherit
       timeout=5  # explicit override
   )

   with config_context(global_cfg):
       with config_context(service_cfg):
           lazy = LazyService()

           print(f"Service: {lazy.service_name}")          # "payment-service" (explicit)
           print(f"Database: {lazy.database_url}")         # Inherited from global
           print(f"Cache: {lazy.cache_enabled}")           # Inherited from global
           print(f"Timeout: {lazy.timeout}")               # 5 (explicit override)
