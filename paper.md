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
    orcid: 0000-0002-6526-3149
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

`ObjectState` provides hierarchical configuration management with dual-axis inheritance: values resolve through both context hierarchy (step → pipeline → global) and class inheritance (specialized → base config). Built on Python's standard library with zero dependencies, it combines lazy dataclass resolution with integrated state tracking, dirty detection, and git-style undo/redo.

# Statement of Need

Scientific workflows often require hundreds of parameters shared across nested execution contexts [@Wilson2014]. Traditional approaches either thread parameters explicitly through every call (brittle) or use global state (untestable) [@Martin2008].

Existing solutions address parts of this: Hydra [@Yadan2019] provides hierarchical composition but not runtime resolution. Sacred [@Greff2017] tracks experiments post-hoc but doesn't determine values at runtime. MobX [@MobX2023] offers reactive state but no inheritance semantics.

ObjectState uniquely combines:

1. **Dual-axis inheritance**: Values resolve through context stack *and* class MRO simultaneously
2. **Integrated state management**: Saved/live state separation with automatic dirty tracking [@Fowler2002]
3. **Git-like history**: Undo/redo with branching timelines
4. **Type-safe lazy evaluation**: Standard dataclasses with deferred resolution [@Claessen2000]

# State of the Field

| Feature | ObjectState | Hydra | pydantic-settings | MobX | Sacred |
|---------|:-----------:|:-----:|:-----------------:|:----:|:------:|
| Dual-axis inheritance | ✓ | — | — | — | — |
| Context hierarchy | ✓ | ✓ | — | — | — |
| Class MRO resolution | ✓ | — | — | — | — |
| Lazy resolution (None sentinel) | ✓ | — | — | — | — |
| Callable parameter inheritance | ✓ | — | — | — | — |
| Provenance tracking | ✓ | — | — | — | — |
| Dirty tracking | ✓ | — | — | ✓ | — |
| Undo/redo with branching | ✓ | — | — | — | — |
| Native dataclass support | ✓ | ¹ | ✓ | — | — |
| Zero dependencies | ✓ | — | — | — | — |

¹ Uses OmegaConf DictConfig, not native dataclasses.

Hydra [@Yadan2019] provides hierarchical *composition* but not runtime *resolution*—once composed, values are static. MobX [@MobX2023] offers reactive state without inheritance semantics. Sacred [@Greff2017] captures configuration post-hoc; ObjectState determines values at runtime based on execution context.

# Software Design

**Lazy Dataclass Factory**: Generates lazy versions of dataclasses using `__getattribute__` interception for deferred resolution.

**Dual-Axis Resolver**: For each field access, traverses the object's MRO checking available contexts for concrete (non-None) values. Uses `contextvars` [@Selivanov2017] for thread-safe context management.

**Provenance Tracking**: Resolution returns not just the value but its source—which scope and type provided it. This enables UI features like placeholder text showing where inherited values originate.

**Object State Registry**: Maintains saved/live state separation with automatic dirty tracking and DAG-based undo/redo history.

## Beyond Dataclasses: Callable Support

ObjectState handles callables (functions, methods) the same way as dataclasses. When given a callable, it extracts parameters from the function signature:

```python
def gaussian_filter(image, sigma=None, preserve_range=None):
    ...

# ObjectState extracts {sigma: None, preserve_range: None} from signature
state = ObjectState(gaussian_filter, scope_id="/plate::step_0::func_0")
state.update_parameter("sigma", 2.0)
```

The `None` sentinel works identically for function kwargs—unset parameters inherit from the context hierarchy. This enables pipeline steps where function parameters participate in the same dual-axis inheritance as dataclass fields.

## Example

```python
@dataclass
class StepConfig(PipelineConfig):
    batch_size: int = None  # None = inherit from context

LazyStepConfig = LazyDataclassFactory.make_lazy_simple(StepConfig)

with config_context(global_cfg):
    with config_context(pipeline_cfg):
        step = LazyStepConfig()
        print(step.batch_size)  # 64 (from PipelineConfig in context)

        # Provenance: where did this value come from?
        from objectstate.dual_axis_resolver import resolve_with_provenance
        value, scope, source_type = resolve_with_provenance(
            StepConfig, "batch_size"
        )
        # scope="/pipeline", source_type=PipelineConfig

        state = ObjectState(step, scope_id="/step_0")
        ObjectStateRegistry.register(state)
        state.update_parameter("batch_size", 128)
        print(state.dirty_fields)  # {'batch_size'}
        ObjectStateRegistry.time_travel_back()
        print(step.batch_size)  # 64 (restored)
```

## Design Principle: None as Sentinel

`None` means "resolve from context." This unifies data model and UI behavior:

- **Data**: `None` triggers dual-axis resolution through context stack and class MRO
- **UI**: Empty fields display placeholder text showing the live-resolved inherited value (via provenance)
- **User**: Clear a field to inherit; enter a value to override

The user's mental model ("empty = inherit") maps directly to resolution semantics.

# Research Application

ObjectState was developed for OpenHCS (Open High-Content Screening) to manage imaging pipeline configurations with hundreds of parameters across processing stages. The framework handles:

- Interactive parameter tuning with immediate feedback
- Experiment branching for comparing configuration strategies
- Hierarchical override patterns (step inherits from pipeline inherits from global)

The zero-dependency design ensures easy integration into scientific software stacks.

# Acknowledgments

This work was supported in part by the Fournier lab at the Montreal Neurological Institute, McGill University. ObjectState was developed within the OpenHCS project before being extracted as a standalone package.

# AI Usage Disclosure

This paper was drafted with assistance from Claude (Anthropic, claude-sonnet-4-5), which was used to structure the manuscript, synthesize information from the codebase and documentation, generate citations, and format content according to JOSS guidelines. All technical content, architectural decisions, research contributions, and the complete ObjectState software implementation are the original intellectual work of the human author(s) developed without AI assistance.

# References
