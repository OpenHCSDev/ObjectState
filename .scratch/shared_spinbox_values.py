"""NRA-selected extraction: one numeric value/control capability, two Qt leaves."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/protocols/widget_adapters.py')
s=p.read_text();index=module_syntax_index(SourceModule.from_source_path(p,s).parse().module)
lines=s.splitlines(keepends=True);edits=[]
classes={n.name:n for _,n in index.indexed_nodes_of_type(ast.ClassDef)}
shared='''    class SpinBoxValueAdapter(PlaceholderStateMixin):
        """Own numeric draft painting and native admission for both Qt spinboxes.

        Qt special-value text is only a view at its numeric minimum. The draft
        owns meaning: literal null displays None; directives display their
        placeholder. A real minimum remains ordinary numeric data.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setRange(*self._default_range)
            self._write_blank_value(self._draft)

        def _read_concrete_value(self):
            return self.value()

        def _write_concrete_value(self, value):
            self.setSpecialValueText("")
            self.setValue(self._numeric_type(value))

        def _paint_special_text(self, text):
            with QSignalBlocker(self):
                self.setSpecialValueText(text)
                self.setValue(self.minimum())

        def _write_null_value(self):
            self._paint_special_text("None")

        def _write_blank_value(self, value):
            self._paint_special_text(self.lineEdit().placeholderText() or repr(value))

        def set_placeholder(self, text):
            self.lineEdit().setPlaceholderText(text)
            if not self._draft.has_value:
                self._paint_special_text(text)

        def configure_range(self, minimum, maximum):
            with QSignalBlocker(self):
                self.setRange(self._numeric_type(minimum), self._numeric_type(maximum))
                self.set_value(self._draft)

        def _signal_sources(self):
            return ((self, self.valueChanged), (self.lineEdit(), self.lineEdit().textEdited))

        def _native_input(self, *arguments):
            # valueChanged normally admits typing first. textEdited additionally
            # admits a minimum typed over null/directives even if Qt's number
            # did not change. Do not publish that same input a second time.
            if self.sender() is self.lineEdit() and isinstance(self._draft, WidgetValue):
                return
            super()._native_input(*arguments)

        def _prepare_input(self):
            self.setSpecialValueText("")


'''
remove={'_read_concrete_value','_write_concrete_value','set_placeholder','configure_range','_signal_sources'}
for name in ('SpinBoxAdapter','DoubleSpinBoxAdapter'):
 n=classes[name]
 for method in n.body:
  if isinstance(method,ast.FunctionDef) and (method.name in remove or(name=='SpinBoxAdapter' and method.name=='__init__')):
   start=min([method.lineno]+[d.lineno for d in method.decorator_list])-1
   edits.append((start,method.end_lineno,''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines).replace('from PyQt6.QtCore import QLocale, QObject','from PyQt6.QtCore import QLocale, QObject, QSignalBlocker')
s=s.replace('    class SpinBoxAdapter(PlaceholderStateMixin,',''+shared+'    class SpinBoxAdapter(SpinBoxValueAdapter,')
s=s.replace('    class DoubleSpinBoxAdapter(PlaceholderStateMixin,','    class DoubleSpinBoxAdapter(SpinBoxValueAdapter,')
s=s.replace('''        Handles None values using special value text mechanism.
        When value is None, displays placeholder text at minimum value.''','''        Shared draft behavior comes from SpinBoxValueAdapter.''')
s=s.replace('''        Handles None values and floating-point ranges.''','''        Shared draft behavior with localized floating-point presentation.''')
s=s.replace('''        _widget_id = "spin_box"''','''        _widget_id = "spin_box"
        _numeric_type = int
        _default_range = (-2147483648, 2147483647)''')
s=s.replace('''        _widget_id = "double_spin_box"''','''        _widget_id = "double_spin_box"
        _numeric_type = float
        _default_range = (-1e308, 1e308)''')
s=s.replace('''            self.setSpecialValueText(" ")
            self.setRange(-1e308, 1e308)  # Default float range
''','')
compile(s,str(p),'exec');p.write_text(s)
