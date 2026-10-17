from dataclasses import dataclass
from objectstate import ObjectState, ObjectStateRegistry, Inherit, LazyDataclassFactory, set_base_config_type, set_global_config
from formbridge.bridge.dto import UiObjectStateFieldMutationRequest, UiObjectStateScopeListRequest
from formbridge.bridge.object_state import ObjectStateFieldMutationService, ObjectStateScopeProjectionService

@dataclass
class Settings:
    text: str | None = None
set_base_config_type(Settings)
set_global_config(Settings, Settings(text='global text'))
Lazy = LazyDataclassFactory.make_lazy_simple(Settings)
state = ObjectState(Lazy(), scope_id='/declared-bridge-journey')
ObjectStateRegistry.register(state)
field = state.fields.text
service = ObjectStateFieldMutationService()
try:
    for value in ('None', '', None):
        result = service.mutate(UiObjectStateFieldMutationRequest.from_fields(
            object_state_scope_id=state.scope_id, field_path='text', value=value,
        ))
        assert result.mutated and not result.errors, result
        assert field.value == value
        assert result.after.raw_value_is_none == (value is None)
        assert not result.after.inherited_value
    result = service.mutate(UiObjectStateFieldMutationRequest.from_fields(
        object_state_scope_id=state.scope_id, field_path='text', reset=True,
    ))
    assert result.mutated and not result.errors, result
    assert isinstance(field.raw, Inherit) and field.value == 'global text'
    assert result.after.inherited_value
    unknown = service.mutate(UiObjectStateFieldMutationRequest.from_fields(
        object_state_scope_id=state.scope_id, field_path='typo', value='bad',
    ))
    assert not unknown.mutated and unknown.errors[0].code == 'ui_object_state_field_not_found'
    summary = ObjectStateScopeProjectionService().summary(state, UiObjectStateScopeListRequest(include_fields=True, include_field_values=True))
    assert summary.fields[0].address.field_path == 'text'
    assert summary.fields[0].inherited_value
    print('real bridge mutation service preserves None/empty/string None; reset inherits; unknown address is rejected; catalog projects handles',flush=True)
    assert ObjectStateRegistry.time_travel_back()
    assert field.value is None
    print('registered history undo retains the original handle and restores literal None',flush=True)
finally:
    ObjectStateRegistry.unregister(state)
