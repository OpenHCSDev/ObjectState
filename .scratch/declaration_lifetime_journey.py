from dataclasses import dataclass, field
from objectstate import ObjectState, Inherit, Unset, LazyDataclassFactory, set_base_config_type, set_global_config
from objectstate.field_access import FieldAccessError

@dataclass
class Config:
    value: int | None = 8
@dataclass
class Settings:
    text: str | None = None
    count: int | None = 4
    config: Config | None = field(default_factory=Config)

set_base_config_type(Settings)
set_global_config(Settings, Settings(count=77, config=Config(91)))
LazyConfig = LazyDataclassFactory.make_lazy_simple(Config)
LazySettings = LazyDataclassFactory.make_lazy_simple(Settings)
state = ObjectState(LazySettings(text=None, config=LazyConfig()), scope_id='declaration-lifetime-journey')
text = state.field(Settings, 'text')
config = state.field(Settings, 'config')
value = state.fields.config.value
# The actual field named "value" must use explicit declaration binding because
# the owning handle also exposes its effective read as .value.
value = state.fields.bind(Settings, ('config', 'value'))
assert config.declaring_type is Settings
assert value.declaring_type is Config
assert config.value.value == 91
assert config.saved_value.value == 91
assert text.value is None
seen=[]
release=text.subscribe(lambda changed:seen.append(text.value))
text.write('edited')
state.restore_saved()
assert text.value is None
assert not text.dirty
assert seen[-1] is None
state.update_object_instance(LazySettings(text='replacement', config=LazyConfig(value=12)))
assert text.value == 'replacement'
assert config.value.value == 12
assert value.value == 12
assert text == state.fields.text
assert hash(text) == hash(state.fields.text)
print('handles survive restore and same-declaration schema replacement; nested owner and payload are distinct',flush=True)
config.write(None)
assert config.value is None
assert config.saved_value.value == 12
assert state.to_object().config is None
config.write(Inherit())
assert config.value.value == 91
config.write(Unset())
assert isinstance(config.value, Unset)
print('nested None, inherited object and absence survive targeted resolution; saved object remains independent',flush=True)
release()
state.update_object_instance(Settings(text='plain', count=Inherit()))
assert state.fields.count.value == 77
print('explicit inheritance resolves on a regular declaration, not just a generated lazy class',flush=True)
@dataclass
class Other:
    text: str = 'other'
state.update_object_instance(Other())
assert not text.present
try:text.write('wrong target')
except FieldAccessError:pass
else:raise AssertionError('a handle retargeted an unrelated declaration')
print('same-name field on an unrelated declaration is not silently targeted',flush=True)
