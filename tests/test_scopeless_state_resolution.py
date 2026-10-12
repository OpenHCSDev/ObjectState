"""An ``ObjectState`` without a scope id resolves its fields like one with a scope id.

Its own object is a layer of its context. A field left unset inherits from another
config of the same object before it inherits from the global config, exactly as an
attribute read on the object does, and the reported source is the object itself.
"""

from dataclasses import dataclass, field

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    config_context,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)
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
    set_global_config_for_editing(
        GlobalConfig, GlobalConfig(WellFilterConfig(well_filter=1, mode="global"))
    )
    return ObjectState(Pipeline(), scope_id=request.param)


def test_unset_field_resolves_to_the_global_value_with_the_global_source(state):
    assert state.parameters[OWN] is None
    assert state.get_resolved_value(OWN) == 1
    assert state.get_provenance(OWN) == ("", WellFilterConfig)


def test_unset_field_inherits_from_a_sibling_config_of_the_same_object(state):
    """The case the OpenHCS dropdown-flash test met with a state without a scope id."""
    state.update_parameter(SIBLING, 7)

    assert state.parameters[OWN] is None
    assert state.get_resolved_value(OWN) == 7
    assert state.get_provenance(OWN) == (state.scope_id, WellFilterConfig)
    assert state.get_resolved_value("path_planning_config.mode") == "global"
    assert state.get_provenance("path_planning_config.mode") == ("", WellFilterConfig)


def test_state_reports_what_an_attribute_read_on_its_object_returns(state):
    state.update_parameter(SIBLING, 7)
    obj = state.to_object()

    with config_context(obj):
        read = obj.path_planning_config.well_filter

    assert read == state.get_resolved_value(OWN) == 7


def test_value_set_on_the_field_wins_and_has_no_inherited_source(state):
    state.update_parameter(SIBLING, 7)
    state.update_parameter(OWN, 9)

    assert state.parameters[OWN] == 9
    assert state.get_resolved_value(OWN) == 9
    assert state.get_provenance(OWN) is None
    assert state.get_resolved_value(SIBLING) == 7


def test_inspection_shows_the_inherited_value_with_its_source(state):
    state.update_parameter(SIBLING, 7)

    inspection = FieldInspection.of(state, OWN)

    assert inspection.raw_value is None
    assert inspection.resolved_value == 7
    assert inspection.provenance is not None
    assert inspection.provenance.source_scope_id == state.scope_id
    assert inspection.provenance.source_type is WellFilterConfig
