"""An ``ObjectState`` without a scope id resolves its fields like one with a scope id.

Its own object is a layer of its context. A field marked Inherit inherits from another
config of the same object before it inherits from the global config, exactly as an
attribute read on the object does, and the reported source is the object itself.
"""

from dataclasses import dataclass, field

import pytest

from objectstate import (
    Inherit,
    LazyDataclassFactory,
    ObjectState,
    config_context,
    mark_global_config_type,
    set_base_config_type,
    set_global_config,
)
from objectstate.field_value import Value
from objectstate.inspection import FieldInspection


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

OWN = "path_planning_config.well_filter"
SIBLING = "well_filter_config.well_filter"


@dataclass
class Pipeline:
    well_filter_config: LazyWellFilterConfig = field(default_factory=LazyWellFilterConfig)
    path_planning_config: LazyPathPlanningConfig = field(default_factory=LazyPathPlanningConfig)


@pytest.fixture(params=[None, "plate"], ids=["no scope id", "scope id"])
def state(request) -> ObjectState:
    set_base_config_type(GlobalConfig)
    set_global_config(
        GlobalConfig, GlobalConfig(
            WellFilterConfig(well_filter=1, mode="global"),
            path_planning_config=LazyPathPlanningConfig(),
        )
    )
    return ObjectState(Pipeline(), scope_id=request.param)


def test_inherited_field_resolves_to_the_global_value_with_the_global_source(state):
    own = state.fields.path_planning_config.well_filter
    assert isinstance(own.raw, Inherit)
    assert own.value == 1
    assert own.provenance == ("", WellFilterConfig)


def test_inherited_field_inherits_from_a_sibling_config_of_the_same_object(state):
    """The case the OpenHCS dropdown-flash test met with a state without a scope id."""
    state.fields.well_filter_config.well_filter.write(7)
    own = state.fields.path_planning_config.well_filter
    assert isinstance(own.raw, Inherit)
    assert own.value == 7
    assert own.provenance == (state.scope_id, WellFilterConfig)
    assert state.fields.path_planning_config.mode.value == "global"
    assert state.fields.path_planning_config.mode.provenance == ("", WellFilterConfig)


def test_state_reports_what_an_attribute_read_on_its_object_returns(state):
    state.fields.well_filter_config.well_filter.write(7)
    obj = state.to_object()

    with config_context(obj):
        read = obj.path_planning_config.well_filter

    assert read == state.fields.path_planning_config.well_filter.value == 7


def test_value_set_on_the_field_wins_and_has_no_inherited_source(state):
    state.fields.well_filter_config.well_filter.write(7)
    own = state.fields.path_planning_config.well_filter
    own.write(9)
    assert own.raw == 9
    assert own.value == 9
    assert own.provenance is None
    assert state.fields.well_filter_config.well_filter.value == 7


def test_inspection_shows_the_inherited_value_with_its_source(state):
    state.fields.well_filter_config.well_filter.write(7)
    inspection = FieldInspection.of(state.fields.path_planning_config.well_filter)
    assert isinstance(inspection.raw_value, Inherit)
    assert inspection.resolved == Value(7)
    assert inspection.provenance is not None
    assert inspection.provenance.source_scope_id == state.scope_id
    assert inspection.provenance.source_type is WellFilterConfig
