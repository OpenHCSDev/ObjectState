"""ObjectState restore lifecycle tests."""

from dataclasses import dataclass

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    get_live_global_config,
    set_base_config_type,
    set_global_config_for_editing,
)


def test_restore_saved_resets_live_global_context_for_descendants():
    """Canceling a global edit must clear both ObjectState and live context."""

    @dataclass
    class GlobalConfig:
        threshold: int = 1

    GlobalConfig._is_global_config = True
    set_base_config_type(GlobalConfig)
    LazyGlobalConfig = LazyDataclassFactory.make_lazy_simple(GlobalConfig)

    saved_global = GlobalConfig(threshold=1)
    set_global_config_for_editing(GlobalConfig, saved_global)

    global_state = ObjectState(saved_global, scope_id="")
    child_state = ObjectState(LazyGlobalConfig(), scope_id="plate::step")
    ObjectStateRegistry.register(global_state, _skip_snapshot=True)
    ObjectStateRegistry.register(child_state, _skip_snapshot=True)

    global_state.update_parameter("threshold", 5)
    assert get_live_global_config(GlobalConfig).threshold == 5
    assert child_state.get_resolved_value("threshold") == 5
    assert child_state.dirty_fields == {"threshold"}

    global_state.restore_saved()

    assert global_state.parameters["threshold"] == 1
    assert get_live_global_config(GlobalConfig).threshold == 1
    assert child_state.get_resolved_value("threshold") == 1
    assert child_state.dirty_fields == set()
