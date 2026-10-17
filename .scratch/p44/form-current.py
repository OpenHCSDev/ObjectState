"""Fresh in-memory configuration and real Qt form; no user files or providers."""
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtTest import QTest
from objectstate import ObjectState, Inherit, LazyDataclassFactory, set_base_config_type, set_global_config
from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager, FormManagerConfig
from pyqt_reactive.theming.color_scheme import ColorScheme

app = QApplication([])
@dataclass
class Settings:
    text: str | None = None
    count: int | None = 4

set_base_config_type(Settings)
set_global_config(Settings, Settings(text='global text', count=77))
Lazy = LazyDataclassFactory.make_lazy_simple(Settings)
state = ObjectState(Lazy(text=None), scope_id='declared-state-journey')
manager = ParameterFormManager(state)
hooks, published = [], []
manager.before_mutation = lambda: hooks.append('mutation')
manager.parameter_changed.connect(lambda name, value: published.append((name, value)))
loop = QEventLoop()
manager.register_form_build_completion_callback(loop.quit)
if not manager.form_build_complete:
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
assert manager.form_build_failure is None, manager.form_build_failure
assert manager.form_build_complete
manager.resize(640, 180)
manager.show()
app.processEvents()
assert manager.grab().save("/home/ts/.cache/agent-scratch/rts-results/p44-form.png")
print("P44_FORM_SCREENSHOT", flush=True)
try:
    print('built', {name: type(widget).__name__ for name, widget in manager.widgets.items()}, flush=True)
    assert manager.widgets['text'].get_value() is None
    assert isinstance(manager.widgets['count'].get_value(), Inherit)
    assert state.fields.count.value == 77
    print('open form preserves literal None and inherited 77 separately', flush=True)
    state.fields.count.write(None)
    app.processEvents()
    assert manager.widgets['count'].get_value() is None
    assert state.to_object().count is None
    print('existing form receives a backend change to literal None', flush=True)
    loop = QEventLoop()
    def changed(_fields):
        if state.fields.text.raw == 'typed':
            loop.quit()
    release = state.fields.subscribe(changed)
    widget = manager.widgets['text']
    widget.setFocus()
    QTest.keyClicks(widget, 'typed')
    if state.fields.text.raw != 'typed':
        QTimer.singleShot(1000, loop.quit)
        loop.exec()
    release()
    assert state.fields.text.raw == 'typed', state.fields.text.raw
    assert state.to_object().text == 'typed'
    print('native Qt keystrokes commit through the original debounce and state callbacks', flush=True)
    before_hooks, before_published = len(hooks), len(published)
    manager.reset_parameter('count')
    app.processEvents()
    assert isinstance(state.fields.count.raw, Inherit)
    assert isinstance(manager.widgets['count'].get_value(), Inherit)
    assert state.fields.count.value == 77
    assert len(hooks) == before_hooks + 1, hooks
    assert len(published) == before_published + 1, published
    assert published[-1][0] == 'count' and isinstance(published[-1][1], Inherit)
    print('reset performs one mutation hook and one publication, restores inherited 77', flush=True)
finally:
    manager.dispose()
    manager.deleteLater()
    app.processEvents()
print('view retired', flush=True)
