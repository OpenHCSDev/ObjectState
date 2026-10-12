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
repository-code: https://github.com/OpenHCSDev/ObjectState
url: https://objectstate.readthedocs.io
---

# Summary

`ObjectState` manages hierarchical configuration held in Python dataclasses. A field left as `None` is inherited, and its value is resolved along two axes: the scope hierarchy (step, plate, global) and the class hierarchy of the config type (specialized to base). One resolver computes every inherited value and returns it together with its source, the scope and the class that supplied it. On top of that the library keeps an editable state per object with a saved baseline, dirty fields, and an undo/redo history with branches. It needs Python 3.11 or later and three packages (`dill`, `pycodify`, `python-introspect`).

# Statement of Need

Scientific workflows often require hundreds of parameters shared across nested execution contexts [@Wilson2014]. Traditional approaches either thread parameters explicitly through every call (brittle) or use global state (untestable) [@Martin2008].

An interactive editor of such configuration must answer two questions for every field: what value applies here, and which object supplied it. If several code paths answer them (attribute access, a preview, a dirty check, a compiler), the answers can drift apart. ObjectState gives each fact one owner and derives the rest:

1. **Dual-axis inheritance in one stated order**: class first, then scope
2. **A source for every resolved value**: the resolver returns the value with the scope and class that supplied it
3. **One holder of the global config**: the state registered at the global scope
4. **Saved and live state**: a saved baseline per state, with dirty fields derived from it [@Fowler2002]
5. **History**: undo/redo over snapshots of all registered states, with branches
6. **Lazy dataclasses**: generated dataclasses whose `None` fields resolve on attribute access [@Claessen2000]

# State of the Field

Hydra [@Yadan2019] composes a hierarchical configuration from files and command-line overrides. pydantic-settings [@Colvin2023] loads and validates settings. Sacred [@Greff2017] configures an experiment, injects parameters into its functions, and records the configuration of each run. MobX [@MobX2023] derives values from observable application state in JavaScript.

ObjectState addresses a different part of the problem: configuration that a user edits while the application runs, where a field of one object inherits from objects in enclosing scopes and from fields of base classes, and where the user interface has to show the inherited value, where it comes from, and whether it differs from what was last saved.

# Software Design

**Lazy dataclass factory**: `LazyDataclassFactory.make_lazy_simple` generates a dataclass whose `__getattribute__` resolves a `None` field in the active context.

**One resolver**: `resolve_with_provenance(type, field)` is the one resolution of a field; a single function behind it walks scopes and classes. It returns `ResolvedField(value, source_scope, source_type)`. Attribute access on a lazy dataclass takes `.value` from this result, and `ObjectState` stores the value and the source from the same call. The active context is a stack of layers held in a `contextvars` variable [@Selivanov2017]; each layer is one object and the scope id it was entered under.

**Class-first precedence**: for each class in the MRO of the type being read, most specific first, every layer is asked from the innermost scope to the outermost, and the first value that is not `None` wins. A value on a more specific class in an outer scope therefore beats a value on a base class in an inner scope. The repository's tests check this order for every subset of nine (class, scope) sites.

**State and registry**: an `ObjectState` holds the flat, editable parameters of one object (nested dataclass fields use dotted paths), a saved baseline, and resolved snapshots of both. `ObjectStateRegistry` maps scope ids such as `"plate::step"` to states and records history.

**Resolved values depend on the registry only**: a state resolves against a layer stack built from the global config and the objects of the states registered at the scopes above it. A `config_context` the caller has entered is set aside for that resolution. Each resolved snapshot keeps the objects it was computed from (`ResolutionSources`); every resolved read compares them, by identity, with the objects the state would be given now, and, while the same scopes are registered, resolves again only the unset fields that can inherit a field stored differently. No caller announces a change. A lazy object that no state owns is the other route: plain attribute access on it reads the entered `config_context`.

**One holder of the global config**: while a state whose object is of the global config type is registered at scope `""`, that state holds the global config. The live global config is the object its parameters describe, and the saved one is the object it last saved; editing, saving, restoring, or undoing that state is that change of the global config. Without such a state, the object given to `set_global_config` is both. `set_global_config` is the one call that replaces it from outside; while a state holds it, the call replaces that state's object. There is one global config per config type per process, and the library does no locking.

## Beyond Dataclasses: Callable Support

An `ObjectState` can also wrap a function. Its parameters and defaults are read from the signature by `python-introspect`:

```python
def threshold_image(image=None, threshold: float = 1.0):
    return image

state = ObjectState(threshold_image, scope_id="plate::step::function_0")
state.get_resolved_value("threshold")  # 1.0
state.type_for_path("threshold")       # threshold_image
```

A function's parameters are held in the same flat store and saved baseline as dataclass fields. They do not inherit: a function parameter left as `None` stays `None`. Inheritance applies to fields of lazy dataclasses.

## Provenance Tracking

For a field the state does not set itself, `get_provenance` returns the source the resolver reported:

```python
step.get_provenance("settings.value")
# ("plate", Settings): the state at scope "plate", read from class Settings
```

It returns `None` when the state sets the field itself. The scope is `""` for the global config. The sources are stored in a dictionary beside the resolved values and written in the same pass, so a user interface can display an inherited value with its origin and navigate to it.

## Example

```python
from dataclasses import dataclass, field
from objectstate import (
    LazyDataclassFactory, ObjectState, ObjectStateRegistry,
    mark_global_config_type, set_base_config_type, set_global_config,
)

@dataclass
class Settings:
    value: str | None = None  # None = inherit

@dataclass
class GlobalConfig:
    settings: Settings = field(default_factory=Settings)

mark_global_config_type(GlobalConfig)
set_base_config_type(GlobalConfig)
LazySettings = LazyDataclassFactory.make_lazy_simple(Settings)

@dataclass
class Holder:  # a plate or a step
    settings: LazySettings = field(default_factory=LazySettings)

set_global_config(GlobalConfig, GlobalConfig(settings=Settings(value="global")))
plate = ObjectState(Holder(settings=LazySettings(value="plate")), scope_id="plate")
ObjectStateRegistry.register(plate)
step = ObjectState(Holder(), scope_id="plate::step")

step.get_resolved_value("settings.value")  # "plate"
step.get_provenance("settings.value")      # ("plate", Settings)

for value in ("first", "second"):
    with ObjectStateRegistry.atomic("edit plate", scope_id="plate"):
        plate.update_parameter("settings.value", value)
step.get_resolved_value("settings.value")  # "second"
step.dirty_fields                          # {"settings.value"}

ObjectStateRegistry.time_travel_back()
step.get_resolved_value("settings.value")  # "first"
```

The step state is never told that the plate changed. It finds out on its next read.

## Design Principle: None as Sentinel

`None` means "inherit":

- **Data**: a `None` field of a lazy dataclass is resolved through the scopes and the class MRO
- **UI**: `LazyDefaultPlaceholderService` formats the inherited value as placeholder text for an empty field
- **User**: clear a field to inherit; enter a value to override

# Research Application

ObjectState was developed for OpenHCS (Open High-Content Screening), an open-source platform for automated microscopy image analysis. OpenHCS registers one state for its global pipeline configuration at scope `""`, and states for each plate, pipeline, step, and step function at scopes below it. A step that leaves a field unset inherits it from the states registered above it and then from the global configuration, without the value being passed through the calls in between.

**Interactive parameter tuning**: when a user clears a field, the form shows the inherited value as a placeholder, and the help control of the field reads `get_provenance` to find the source.

**Undo and branches**: undo and redo call the registry's `time_travel_back` and `time_travel_forward`. An edit made after travelling back keeps the abandoned future as an automatically named branch, so an earlier configuration can be revisited.

**Dirty tracking**: a field is dirty when its live and saved resolved values differ, so a step is also marked when an unsaved edit of its plate changes what the step inherits.

# Acknowledgments

This work was supported in part by the Fournier lab at the Montreal Neurological Institute, McGill University. ObjectState was developed within the OpenHCS project before being extracted as a standalone package.

# AI Usage Disclosure

This paper was drafted with assistance from Claude (Anthropic, claude-sonnet-4-5), which was used to structure the manuscript, synthesize information from the codebase and documentation, generate citations, and format content according to JOSS guidelines. The manuscript was revised for release 4.0.0 with Claude (claude-opus-5-5), which checked each statement against the source. Commits in the repository carry `Co-Authored-By: Claude` trailers where a Claude model assisted with the code, including the commits that introduced the resolution and global-config design described here. Technical content, architectural decisions, and research contributions are the work of the human author.

# References
