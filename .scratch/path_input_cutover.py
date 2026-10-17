import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/widgets/enhanced_path_widget.py');s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
c=next(n for _,n in idx.indexed_nodes_of_type(ast.ClassDef)if n.name=='EnhancedPathWidget')
for n in c.body:
 if not isinstance(n,ast.FunctionDef):continue
 if n.name in {'get_value','set_value','connect_change_signal','disconnect_change_signal'}:edits.append((n.lineno-1,n.end_lineno,''))
 elif n.name in {'get_path','set_path'}:
  text=''.join(lines[n.lineno-1:n.end_lineno]).replace('def get_path(', 'def _read_concrete_value(',1).replace('def set_path(', 'def _write_concrete_value(',1)
  text=text.replace('self.path_input.blockSignals(True)','previous = self.path_input.blockSignals(True)').replace('self.path_input.blockSignals(False)','self.path_input.blockSignals(previous)')
  edits.append((n.lineno-1,n.end_lineno,text))
edits.append((c.end_lineno,c.end_lineno,'\n    def _signal_sources(self):\n        return ((self, self.path_changed),)\n'))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines).replace('self.set_path(current_value)','self.set_value(current_value)').replace('self.set_path(path_obj)','self.set_value(path_obj)');compile(s,str(p),'exec');p.write_text(s)
