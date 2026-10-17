"""Move Qt adapter field-value meaning and signal lifetime into its existing mixin."""
import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/protocols/widget_adapters.py')
s=P.read_text();s=s.replace('from typing import Any','from typing import Any\nfrom objectstate.field_value import FieldValue, Inherit, Unset, Value')
MIXIN='''class WidgetValue(Value):
    """A concrete draft read from its control, not a second stored model value."""
    __slots__ = ('reader',)

    def __init__(self, reader):
        self.reader = reader

    @property
    def value(self):
        return self.reader()


class PlaceholderStateMixin(PlaceholderStateTrackable):
    """Own one input draft and its native signal subscriptions.

    Inherit and Unset are retained as distinct input states. Concrete input lives
    in the Qt control and is read lazily, so incomplete text is not parsed while
    the user is typing. Model paints never publish input events.
    """
    widget_capabilities = frozenset({WidgetCapability.PLACEHOLDER_STATE})

    def __init__(self, *args, **kwargs):
        self._draft = Unset()
        self._input_callbacks = []
        self._native_connections = {}
        self._cached_placeholder_text = None
        self._cached_placeholder_resolved_value = None
        super().__init__(*args, **kwargs)

    def _signal_sources(self):
        return ()

    def _ensure_input_tracking(self):
        for owner, signal in self._signal_sources():
            if owner not in self._native_connections:
                signal.connect(self._native_input)
                self._native_connections[owner] = signal

    def _native_input(self, *arguments):
        self._prepare_input()
        self._draft = WidgetValue(self._read_concrete_value)
        self.clear_placeholder_cache()
        self._apply_draft_style()
        for callback in tuple(self._input_callbacks):
            callback(self.get_value())

    def _prepare_input(self):
        pass

    def _apply_draft_style(self):
        pass

    def _write_blank_value(self, value):
        self._write_concrete_value(None)

    def get_value(self):
        self._ensure_input_tracking()
        return self._draft.resolve(lambda: Inherit())

    def set_value(self, value):
        self._ensure_input_tracking()
        draft = FieldValue.of(value)
        previous = self.blockSignals(True)
        try:
            self._draft = draft
            if draft.has_value:
                self._write_concrete_value(value)
                if value is not None:
                    self._draft = WidgetValue(self._read_concrete_value)
            else:
                self._write_blank_value(value)
            self._apply_draft_style()
        finally:
            self.blockSignals(previous)

    def connect_change_signal(self, callback):
        self._ensure_input_tracking()
        if callback not in self._input_callbacks:
            self._input_callbacks.append(callback)

    def disconnect_change_signal(self, callback):
        if callback in self._input_callbacks:
            self._input_callbacks.remove(callback)

    def has_placeholder_state(self):
        return self._draft.inherited

    def mark_placeholder_state(self):
        self._draft = Inherit()

    def clear_placeholder_state(self):
        if self._draft.inherited:
            self._draft = WidgetValue(self._read_concrete_value)
        self.clear_placeholder_cache()

    def cached_placeholder_text(self):
        return self._cached_placeholder_text

    def set_cached_placeholder_text(self, text):
        self._cached_placeholder_text = text

    def cached_placeholder_resolved_value(self):
        return self._cached_placeholder_resolved_value

    def set_cached_placeholder_resolved_value(self, value):
        self._cached_placeholder_resolved_value = value

    def clear_placeholder_cache(self):
        self._cached_placeholder_text = None
        self._cached_placeholder_resolved_value = None
'''
parsed=SourceModule.from_source_path(P,s).parse();nodes=[n for _,n in module_syntax_index(parsed.module).indexed_nodes_of_type(ast.ClassDef)];edits=[]
for c in nodes:
 if c.name=='PlaceholderStateMixin':
  edits.append((c.lineno-1,c.end_lineno,textwrap.indent(MIXIN,' '*c.col_offset)+'\n'));continue
 if c.name not in {'LineEditAdapter','KeySequenceEditAdapter','SpinBoxAdapter','DoubleSpinBoxAdapter','ComboBoxAdapter','CheckBoxAdapter','CheckboxGroupAdapter'}:continue
 methods={n.name:n for n in c.body if isinstance(n,ast.FunctionDef)}
 for name in ('get_value','set_value'):
  n=methods[name];lines=s.splitlines(keepends=True);original=''.join(lines[n.lineno-1:n.end_lineno]);newname='_read_concrete_value'if name=='get_value'else'_write_concrete_value'
  replacement=original.replace('def '+name+'(', 'def '+newname+'(',1)
  if name=='get_value' and c.name=='LineEditAdapter':replacement=replacement.replace('return None if text == "" else text','return text')
  if name=='get_value' and c.name in {'SpinBoxAdapter','DoubleSpinBoxAdapter'}:
   replacement=' '*n.col_offset+'def _read_concrete_value(self):\n'+' '*(n.col_offset+4)+'return self.value()\n'
  if name=='get_value' and c.name=='ComboBoxAdapter':replacement=replacement.replace('return None','return Unset()')
  if c.name=='CheckboxGroupAdapter':
   if name=='get_value':replacement=' '*n.col_offset+'def _read_concrete_value(self):\n'+' '*(n.col_offset+4)+'return [value for value, checkbox in self.checkbox_items() if checkbox.isChecked()]\n'
   else:replacement=' '*n.col_offset+'def _write_concrete_value(self, value):\n'+' '*(n.col_offset+4)+'for member, checkbox in self.checkbox_items():\n'+' '*(n.col_offset+8)+'checkbox.set_value(member in value if value is not None else False)\n'
  edits.append((n.lineno-1,n.end_lineno,replacement))
 for name in ('connect_change_signal','disconnect_change_signal','_make_checkbox_group_handler','has_placeholder_state'):
  if name in methods:
   n=methods[name];edits.append((n.lineno-1,n.end_lineno,''))
 if c.name=='KeySequenceEditAdapter':
  n=methods['__init__'];edits.append((n.lineno-1,n.end_lineno,''))
 signal={'LineEditAdapter':'textChanged','KeySequenceEditAdapter':'editingFinished','SpinBoxAdapter':'valueChanged','DoubleSpinBoxAdapter':'valueChanged','ComboBoxAdapter':'currentIndexChanged','CheckBoxAdapter':'stateChanged'}.get(c.name)
 indent=' '*(c.col_offset+4)
 if signal:hook=f'\n{indent}def _signal_sources(self):\n{indent}    return ((self, self.{signal}),)\n'
 else:hook=f'''\n{indent}def _signal_sources(self):
{indent}    return tuple((checkbox, checkbox.stateChanged) for checkbox in self.checkbox_widgets())

{indent}def _prepare_input(self):
{indent}    for checkbox in self.checkbox_widgets():
{indent}        checkbox.convert_placeholder_to_concrete()

{indent}def _write_blank_value(self, value):
{indent}    for checkbox in self.checkbox_widgets():
{indent}        checkbox.set_value(value)
'''
 edits.append((c.end_lineno,c.end_lineno,hook))
lines=s.splitlines(keepends=True)
for start,end,text in sorted(edits,reverse=True):lines[start:end]=[text]
s=''.join(lines);ast.parse(s);P.write_text(s)
