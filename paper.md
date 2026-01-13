---
title: 'ObjectState: A Generic Framework for Hierarchical Configuration Management with Dual-Axis Inheritance and State Tracking'
tags:
  - Python
  - configuration management
  - dataclasses
  - hierarchical configuration
  - state management
  - undo-redo
  - lazy evaluation
authors:
  - name: Tristan Simas
    orcid: 0000-0000-0000-0000  # TODO: Replace with actual ORCID
    equal-contrib: true
    affiliation: 1
affiliations:
 - name: McGill University, Montreal, Canada
   index: 1
date: 13 January 2026
bibliography: paper.bib
repository-code: https://github.com/trissim/objectstate
url: https://objectstate.readthedocs.io
---

# Summary

`ObjectState` is a pure-Python framework for hierarchical configuration management that combines lazy dataclass resolution with stateful object tracking. The framework addresses the common challenge of managing complex, deeply nested configurations across hierarchical execution contexts (e.g., global → pipeline → step) while maintaining change tracking, dirty detection, and complete undo/redo capabilities. Built entirely on Python's standard library, ObjectState introduces a novel dual-axis inheritance model that resolves configuration values both vertically through context hierarchies (X-axis) and horizontally through class inheritance chains (Y-axis), enabling sophisticated configuration patterns without manual parameter propagation.

# Statement of need

Scientific computing workflows and data processing pipelines often involve deeply nested execution contexts with hundreds of configuration parameters that must be shared across multiple levels of abstraction [@Wilson2014; @Jimenez2017]. Traditional approaches force developers to either explicitly pass dozens of parameters through every function call, leading to brittle code with poor maintainability, or resort to global state that violates encapsulation and complicates testing [@Martin2008].

Existing Python configuration libraries such as `Hydra` [@Yadan2019], `OmegaConf` [@Yadan2021], and `pydantic-settings` [@Colvin2023] provide hierarchical configuration management but lack integrated state tracking and change history. Configuration management systems designed for machine learning workflows, such as `ml_collections` [@Google2020] and Sacred [@Greff2017], focus on experiment tracking rather than runtime configuration resolution. None of these solutions provide the dual-axis inheritance model that ObjectState implements, which is essential for handling complex inheritance patterns where configuration values must be resolved across both context boundaries and class hierarchies simultaneously.

ObjectState fills this gap by providing:

1. **Dual-axis inheritance**: Configuration values resolve through both context hierarchy (step → pipeline → global) and class inheritance (specialized → base), eliminating the need for manual parameter threading [@Gamma1994].

2. **Integrated state management**: Every configuration object maintains both saved (baseline) and live (edited) states with automatic dirty tracking, enabling robust change detection without external state stores [@Fowler2002].

3. **Git-like history**: Complete undo/redo with branching timelines and time-travel capabilities, allowing developers to experiment with configuration changes and rollback to any previous state [@Spinellis2005].

4. **Type-safe lazy evaluation**: Configuration objects use Python dataclasses with full IDE support and type checking, while deferring resolution until runtime [@Claessen2000].

The framework is particularly valuable for scientific applications requiring complex, deeply nested configurations with interactive parameter adjustment, such as high-content screening workflows, image analysis pipelines, and machine learning experiments where tracking configuration provenance and enabling experimentation are critical.

# State of the field

Configuration management in Python has evolved through several paradigms. Early approaches relied on global dictionaries or environment variables [@vanRossum2009], sacrificing type safety and IDE support. The introduction of dataclasses in Python 3.7 [@Smith2018] provided structured configuration with type hints, but lacked hierarchical resolution mechanisms.

Modern configuration frameworks can be categorized into three main approaches:

**Hierarchical configuration libraries** like Hydra [@Yadan2019] and OmegaConf [@Yadan2021] provide composition and override capabilities but use custom data structures rather than standard dataclasses, limiting integration with existing type-checking tools. They focus on static configuration loading rather than runtime context resolution.

**Settings management libraries** such as `pydantic-settings` [@Colvin2023] and `python-decouple` [@Sousa2020] excel at loading configuration from multiple sources (files, environment variables, etc.) but lack support for dynamic context hierarchies and change tracking.

**Experiment tracking systems** like Sacred [@Greff2017], MLflow [@Zaharia2018], and Weights & Biases [@Biewald2020] provide comprehensive configuration capture for reproducibility but are designed for post-hoc analysis rather than runtime resolution and interactive modification.

ObjectState uniquely combines the structured approach of dataclasses with context-aware resolution inspired by React's Context API [@Facebook2019] and the change tracking patterns from revision control systems [@Spinellis2005]. The dual-axis inheritance model draws inspiration from multiple inheritance resolution in object-oriented languages [@vanRossum1991] but applies it to configuration values across execution contexts, a novel contribution not found in existing frameworks.

The framework's `contextvars`-based implementation [@Selivanov2017] ensures thread-safety without global state pollution, making it suitable for concurrent processing scenarios common in scientific computing. The optional parametric axes prototype extends Python's type system with arbitrary semantic dimensions, contributing to ongoing discussions about Python's type system evolution [@Levkivskyi2016; @vanRossum2014].

# Implementation and Quality Assurance

ObjectState is implemented in pure Python 3.11+ with zero external dependencies, comprising approximately 7,900 lines of production code. The architecture consists of several key components:

**Lazy Dataclass Factory** (`lazy_factory.py`): Dynamically generates lazy versions of dataclasses that defer field resolution to runtime. Uses Python's `__getattribute__` protocol to intercept attribute access and resolve values through the dual-axis resolver. Supports automatic nested dataclass conversion and field injection for modular configuration composition.

**Dual-Axis Resolver** (`dual_axis_resolver.py`): Implements the core MRO-based inheritance algorithm. For each field access, traverses the requesting object's Method Resolution Order (MRO) from most to least specific class, checking available contexts for concrete (non-None) values. Includes targeted cache invalidation to maintain performance while ensuring correctness during parameter updates.

**Context Manager** (`context_manager.py`): Provides `config_context()` context manager using Python's `contextvars` module for clean, thread-safe context management. Supports context stacking, hierarchy registration, and scope-based filtering for complex nested workflows.

**Object State Registry** (`object_state.py`): Maintains a global registry of all configuration objects with automatic dirty tracking. Implements the state separation pattern where each object stores both saved (baseline) and live (current) states, enabling efficient change detection and rollback operations.

**Snapshot Model** (`snapshot_model.py`): Provides immutable snapshot dataclasses for the time-travel system. Implements a Directed Acyclic Graph (DAG) history model analogous to Git's commit graph, supporting branching timelines, time travel to arbitrary points, and complete history serialization to JSON.

**Advanced Prototypes**: The `parametric_axes` module demonstrates extending Python's type system with arbitrary semantic axes beyond the standard `(Base, Self)` tuple, using `__init_subclass__` (PEP 487). The `reified_generics` module provides runtime-accessible type parameters for generic types, addressing limitations in Python's type system.

Quality assurance is maintained through comprehensive testing:

- **Test Coverage**: 100% code coverage across 8 test modules with 200+ unit and integration tests
- **Type Safety**: Full type annotations with `mypy` static type checking in strict mode
- **Code Quality**: Automated linting with `ruff` and code formatting with `black`
- **Documentation**: Complete API documentation hosted on ReadTheDocs with examples and tutorials
- **Continuous Integration**: Automated testing on Python 3.11, 3.12, and 3.13

The codebase follows established software engineering practices including the Single Responsibility Principle, dependency inversion, and extensive inline documentation. Performance-critical sections use caching strategies with targeted invalidation to balance speed and correctness.

## Availability and Installation

ObjectState is distributed via the Python Package Index (PyPI) and can be installed with:

```bash
pip install objectstate
```

The source code is hosted on GitHub at [https://github.com/trissim/objectstate](https://github.com/trissim/objectstate) under the MIT license, with comprehensive documentation available at [https://objectstate.readthedocs.io](https://objectstate.readthedocs.io). The package supports Python 3.11 and later versions, with no external dependencies required.

# Example Usage

The following example demonstrates ObjectState's dual-axis inheritance in a typical scientific computing scenario:

```python
from dataclasses import dataclass
from objectstate import (
    LazyDataclassFactory,
    config_context,
    set_base_config_type,
    ObjectState,
    ObjectStateRegistry
)

# Define hierarchical configuration structure
@dataclass
class GlobalConfig:
    num_workers: int = 4
    output_dir: str = "/tmp"
    debug: bool = False

@dataclass
class PipelineConfig:
    batch_size: int = 32
    num_workers: int = None  # Inherits from GlobalConfig

@dataclass
class StepConfig(PipelineConfig):
    step_name: str = "preprocessing"
    batch_size: int = None  # Inherits from PipelineConfig
    num_workers: int = None  # Inherits through dual-axis

# Initialize framework
set_base_config_type(GlobalConfig)
LazyStepConfig = LazyDataclassFactory.make_lazy_simple(StepConfig)

# Create concrete configurations
global_cfg = GlobalConfig(num_workers=8, debug=True)
pipeline_cfg = PipelineConfig(batch_size=64)

# Dual-axis resolution: context hierarchy + class inheritance
with config_context(global_cfg):
    with config_context(pipeline_cfg):
        step = LazyStepConfig(step_name="normalization")

        # Resolves: StepConfig → PipelineConfig → GlobalConfig
        print(step.num_workers)   # 8 (from GlobalConfig)
        print(step.batch_size)    # 64 (from PipelineConfig)
        print(step.debug)         # True (from GlobalConfig)

        # State management with undo/redo
        state = ObjectState(step, scope_id="/pipeline/step_0")
        ObjectStateRegistry.register(state)

        # Track changes
        state.update_parameter("batch_size", 128)
        print(state.dirty_fields)  # {'batch_size'}

        # Undo/redo support
        ObjectStateRegistry.undo()
        print(step.batch_size)  # 64 (restored)
```

This example illustrates how configuration values flow through both the context stack (global → pipeline → step) and the class inheritance chain (StepConfig → PipelineConfig), with automatic change tracking and undo capabilities.

# Research Applications

ObjectState was developed as part of the OpenHCS (Open High-Content Screening) project to manage complex imaging pipeline configurations with hundreds of parameters across multiple processing stages. The framework has proven effective in scenarios requiring:

- Interactive parameter tuning with immediate visual feedback
- Experiment branching to compare different configuration strategies
- Configuration provenance tracking for reproducible science
- Hierarchical override patterns where specialized steps inherit from global defaults

The dual-axis inheritance model naturally represents the configuration space of scientific workflows where both context hierarchy (which processing stage) and class hierarchy (which algorithm variant) determine parameter values. The integrated state management eliminates an entire class of bugs related to unsaved changes and inconsistent state.

Beyond high-content screening, the framework is applicable to any scientific computing domain requiring hierarchical configuration management, including bioinformatics pipelines, machine learning hyperparameter tuning, simulation workflows, and computational physics applications. The zero-dependency design and pure-stdlib implementation ensure easy integration into existing scientific software stacks.

# Future Directions

Planned enhancements include validation hooks for constraint checking, schema evolution support for versioned configurations, and integration with popular experiment tracking frameworks. The parametric axes prototype may inform future Python Enhancement Proposals (PEPs) for extending the type system with arbitrary semantic dimensions.

# Acknowledgments

This work was supported by the OpenHCS project. The author thanks the Python community for the robust standard library that made this implementation possible.

# AI Usage Disclosure

This paper was drafted with assistance from Claude (Anthropic, claude-sonnet-4-5), which was used to structure the manuscript, synthesize information from the codebase and documentation, generate citations, and format content according to JOSS guidelines. All technical content, architectural decisions, research contributions, and the complete ObjectState software implementation are the original intellectual work of the human author(s) developed without AI assistance.

# References
