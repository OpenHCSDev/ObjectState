"""One resolution answers "what does this field resolve to", for reads and for display.

Attribute access on a lazy config and ``ObjectState`` both take their value from
``resolve_with_provenance``. Its answers are held by the layer stack of the context
they were computed from, so no other context can drop or replace them.
"""

import gc
import threading
import weakref
from dataclasses import dataclass, field

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    build_context_stack,
    config_context,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
    set_live_global_config,
)
from objectstate.context_manager import get_base_global_config, get_context_layer_stack
from objectstate.dual_axis_resolver import resolve_with_provenance


@dataclass
class WellFilterConfig:
    well_filter: int | None = None
    mode: str | None = None


@dataclass
class PathPlanningConfig(WellFilterConfig):
    suffix: str | None = None


@dataclass
class GlobalConfig:
    well_filter_config: WellFilterConfig = field(default_factory=WellFilterConfig)
    path_planning_config: PathPlanningConfig = field(default_factory=PathPlanningConfig)


mark_global_config_type(GlobalConfig)
LazyWellFilterConfig = LazyDataclassFactory.make_lazy_simple(WellFilterConfig)
LazyPathPlanningConfig = LazyDataclassFactory.make_lazy_simple(PathPlanningConfig)
LEAF_FIELDS = ("well_filter", "mode", "suffix")


@dataclass
class Pipeline:
    well_filter_config: LazyWellFilterConfig = field(default_factory=LazyWellFilterConfig)
    path_planning_config: LazyPathPlanningConfig = field(default_factory=LazyPathPlanningConfig)


@dataclass
class Step:
    path_planning_config: LazyPathPlanningConfig = field(default_factory=LazyPathPlanningConfig)


def _use_global(saved: GlobalConfig, live: GlobalConfig | None = None) -> None:
    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, saved)
    if live is not None:
        set_live_global_config(GlobalConfig, live)


def test_attribute_read_and_provenance_agree_when_a_layer_has_no_scope_id():
    """The reproducer of issue #29."""
    set_base_config_type(GlobalConfig)
    outer = GlobalConfig(WellFilterConfig(well_filter=1))
    inner = GlobalConfig(WellFilterConfig(well_filter=2))

    with config_context(outer, use_live_global=False, scope_id=""):
        with config_context(inner):
            read = LazyWellFilterConfig().well_filter
            resolved = resolve_with_provenance(LazyWellFilterConfig, "well_filter")

    assert read == 2
    assert resolved == (2, None, WellFilterConfig)


def test_layers_entered_without_scope_ids_supply_values_with_their_type():
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1, mode="include")))
    pipeline = Pipeline(path_planning_config=LazyPathPlanningConfig(suffix="_out"))

    with config_context(pipeline):
        with config_context(Step()):
            reads = {name: getattr(LazyPathPlanningConfig(), name) for name in LEAF_FIELDS}
            resolved = {
                name: resolve_with_provenance(LazyPathPlanningConfig, name) for name in LEAF_FIELDS
            }

    assert reads == {"well_filter": 1, "mode": "include", "suffix": "_out"}
    assert resolved == {
        "well_filter": (1, "", WellFilterConfig),
        "mode": ("include", "", WellFilterConfig),
        "suffix": ("_out", None, PathPlanningConfig),
    }


def _global_alone():
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1)))
    return Step(), [], "plate::step"


def _ancestor_supplies_same_type():
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1)))
    pipeline = Pipeline(path_planning_config=LazyPathPlanningConfig(well_filter=5, suffix="_p"))
    return Step(), [("plate", pipeline)], "plate::step"


def _ancestor_supplies_base_type_only():
    _use_global(GlobalConfig(path_planning_config=PathPlanningConfig(mode="exclude")))
    pipeline = Pipeline(well_filter_config=LazyWellFilterConfig(well_filter=8, mode="include"))
    return Step(), [("plate", pipeline)], "plate::step"


def _two_ancestors():
    _use_global(GlobalConfig(WellFilterConfig(mode="include")))
    plate = Pipeline(path_planning_config=LazyPathPlanningConfig(well_filter=5))
    group = Pipeline(path_planning_config=LazyPathPlanningConfig(suffix="_g"))
    return Step(), [("plate", plate), ("plate::group", group)], "plate::group::step"


def _global_config_among_ancestors():
    saved = GlobalConfig(WellFilterConfig(well_filter=1))
    _use_global(saved)
    pipeline = Pipeline(path_planning_config=LazyPathPlanningConfig(suffix="_p"))
    return Step(), [("", saved), ("plate", pipeline)], "plate::step"


def _object_sets_its_own_value():
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1)))
    step = Step(path_planning_config=LazyPathPlanningConfig(well_filter=3))
    return step, [("plate", Pipeline())], "plate::step"


def _saved_global_differs_from_live():
    _use_global(
        saved=GlobalConfig(WellFilterConfig(well_filter=1)),
        live=GlobalConfig(WellFilterConfig(well_filter=9, mode="live-only")),
    )
    return Step(), [("plate", Pipeline())], "plate::step"


def _nothing_supplies_a_value():
    _use_global(GlobalConfig())
    return Step(), [("plate", Pipeline())], "plate::step"


@pytest.mark.parametrize(
    "arrangement",
    [
        _global_alone,
        _ancestor_supplies_same_type,
        _ancestor_supplies_base_type_only,
        _two_ancestors,
        _global_config_among_ancestors,
        _object_sets_its_own_value,
        _saved_global_differs_from_live,
        _nothing_supplies_a_value,
    ],
)
def test_attribute_read_equals_what_object_state_reports(arrangement):
    """For every stack ``build_context_stack`` builds, a read is the reported value."""
    step, ancestors, scope_id = arrangement()

    with build_context_stack(step, ancestors, scope_id, use_live=False):
        reads = {name: getattr(step.path_planning_config, name) for name in LEAF_FIELDS}
        sources = {
            name: resolve_with_provenance(LazyPathPlanningConfig, name)[1:]
            for name in LEAF_FIELDS
            if object.__getattribute__(step.path_planning_config, name) is None
        }

    reported, provenance = ObjectState.resolve_saved_object(
        step, scope_id=scope_id, ancestor_objects_with_scopes=ancestors
    )
    assert {name: getattr(reported.path_planning_config, name) for name in LEAF_FIELDS} == reads
    assert {
        name: provenance[f"path_planning_config.{name}"] for name in sources
    } == sources


def test_attribute_read_equals_what_object_state_reports_for_a_global_config():
    """The global config is resolved against its declared defaults, which mask the saved one."""
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1, mode="saved")))
    edited = GlobalConfig(
        well_filter_config=WellFilterConfig(mode="edited"),
        path_planning_config=PathPlanningConfig(suffix="_e"),
    )

    with build_context_stack(edited, current_scope_id="", use_live=False):
        scopes = [layer.scope_id for layer in get_context_layer_stack().layers]
        reads = {name: getattr(LazyPathPlanningConfig(), name) for name in LEAF_FIELDS}
        resolved = {
            name: resolve_with_provenance(LazyPathPlanningConfig, name).value
            for name in LEAF_FIELDS
        }

    assert scopes == ["", "", ""]
    assert reads == resolved == {"well_filter": None, "mode": "edited", "suffix": "_e"}


def test_declared_default_is_read_and_reported_alike():
    @dataclass
    class Display:
        dimension_mode: str = "stack"

    @dataclass
    class Streaming(Display):
        port: int | None = None

    @dataclass
    class StreamingGlobal:
        workers: int = 1

    lazy_streaming = LazyDataclassFactory.make_lazy_simple(Streaming)
    set_base_config_type(StreamingGlobal)

    with config_context(StreamingGlobal(), scope_id=""):
        read = lazy_streaming().dimension_mode
        resolved = resolve_with_provenance(lazy_streaming, "dimension_mode")

    assert read == "stack"
    assert resolved.value == "stack"


def test_answers_survive_another_thread_entering_and_leaving_a_context():
    """Issue #33: a context's answers are not dropped by a context in another thread."""
    saved_global = GlobalConfig(WellFilterConfig(well_filter=1))
    first_resolved = threading.Event()
    other_thread_done = threading.Event()
    answers = []
    errors = []

    def resolve_twice():
        try:
            _use_global(saved_global)  # the global config is per thread
            with config_context(Pipeline(), scope_id="plate"):
                answers.append(resolve_with_provenance(LazyPathPlanningConfig, "well_filter"))
                first_resolved.set()
                assert other_thread_done.wait(timeout=10)
                answers.append(resolve_with_provenance(LazyPathPlanningConfig, "well_filter"))
        except BaseException as error:  # noqa: BLE001 - reported by the main thread
            errors.append(error)
            first_resolved.set()

    def enter_and_leave():
        try:
            assert first_resolved.wait(timeout=10)
            _use_global(saved_global)  # the global config is per thread
            other = Pipeline(path_planning_config=LazyPathPlanningConfig(well_filter=7))
            with config_context(other, scope_id="other"):
                answers.append(resolve_with_provenance(LazyPathPlanningConfig, "well_filter"))
        except BaseException as error:  # noqa: BLE001 - reported by the main thread
            errors.append(error)
        finally:
            other_thread_done.set()

    threads = [threading.Thread(target=resolve_twice), threading.Thread(target=enter_and_leave)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    first, other, second = answers
    assert first == (1, "", WellFilterConfig)
    assert other == (7, "other", PathPlanningConfig)
    # The very object computed before the other thread's context came and went.
    assert second is first


def test_answers_are_dropped_with_the_context_they_were_computed_from():
    _use_global(GlobalConfig(WellFilterConfig(well_filter=1)))

    with config_context(Pipeline(), scope_id="plate"):
        stack = get_context_layer_stack()
        resolved = resolve_with_provenance(LazyPathPlanningConfig, "well_filter")
        assert stack.resolved_fields[(LazyPathPlanningConfig, "well_filter")] is resolved
        with config_context(Step(), scope_id="plate::step"):
            assert get_context_layer_stack() is not stack
            assert get_context_layer_stack().layers[:-1] == stack.layers
        assert get_context_layer_stack() is stack
        assert resolve_with_provenance(LazyPathPlanningConfig, "well_filter") is resolved
        stack_alive = weakref.ref(stack)

    del stack
    gc.collect()
    assert stack_alive() is None


def test_base_global_config_is_never_silently_absent(monkeypatch):
    """A global config that cannot be looked up raises; it is not replaced by ``None``."""
    monkeypatch.delattr("objectstate.global_config.get_current_global_config")
    with pytest.raises(ImportError, match="get_current_global_config"):
        get_base_global_config()
