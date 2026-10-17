from dataclasses import dataclass
from objectstate import ObjectState, Inherit, Unset, set_base_config_type
from objectstate.field_value import Value
from objectstate.inspection import FieldInspection
from formbridge.bridge.object_state import ObjectStateFieldSemanticProjection
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pyqt_reactive.protocols import SpinBoxAdapter, DoubleSpinBoxAdapter
from pyqt_reactive.widgets.no_scroll_spinbox import NoScrollSpinBox, NoScrollDoubleSpinBox

@dataclass
class Config:
    text: str | None = None
set_base_config_type(Config)
for datum in (None, Unset(), 'None', ''):
    state = ObjectState(Config(text=datum))
    field = state.fields.text
    inspection = FieldInspection.of(field)
    projected = ObjectStateFieldSemanticProjection.of(field)
    assert inspection.resolved.project(lambda v: v) == datum
    if isinstance(datum, Unset):
        assert projected.resolved_json_value == 'Unset()'
        assert projected.resolved_value_preview.type_name == 'Unset'
        assert projected.resolved_value_preview.text == 'Unset()'
        assert not projected.resolved_value_is_none
    else:
        assert projected.resolved_json_value == datum
for directive in (Unset(), Inherit()):
    assert directive.project(lambda v: v) is directive
app = QApplication.instance() or QApplication([])
for kind in (SpinBoxAdapter, DoubleSpinBoxAdapter, NoScrollSpinBox, NoScrollDoubleSpinBox):
    widget = kind(); widget.show(); app.processEvents()
    calls=[]; widget.connect_change_signal(calls.append)
    for datum in (Inherit(), Unset(), None, Value(None), 0, widget.minimum()):
        widget.set_value(datum)
        expected = datum.resolve(lambda: Inherit()) if isinstance(datum, Value) else datum
        assert widget.get_value() == expected, (kind,datum,widget.get_value())
        if datum is None or datum == Value(None):
            assert widget.text() == 'None', (kind,widget.text())
    assert calls == [], calls
    widget.configure_range(-10,10)
    for datum in (None, Inherit(), Unset()):
        widget.set_value(datum)
        widget.lineEdit().selectAll(); QTest.keyClicks(widget.lineEdit(), '0')
        assert widget.get_value() == 0, (kind,datum,widget.get_value())
        assert calls[-1] == 0, (kind, datum, calls, widget.value(), widget.text())
        widget.set_value(datum)
        widget.lineEdit().selectAll(); QTest.keyClicks(widget.lineEdit(), '-10')
        assert widget.get_value() == -10, (kind,datum,widget.get_value(),widget.text())
    widget.close(); widget.deleteLater()
print('real Qt numeric controls: distinct literal null/directives/minima, wrapped Values, native zero/minimum input; bridge renders absent member, not null',flush=True)
