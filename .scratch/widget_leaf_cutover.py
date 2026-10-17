import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive')
def transform(path,visitor):
 s=path.read_text();parsed=SourceModule.from_source_path(path,s).parse();idx=module_syntax_index(parsed.module);edits=visitor(s,idx);lines=s.splitlines(keepends=True)
 for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
 out=''.join(lines);ast.parse(out,filename=str(path));path.write_text(out)
def whole(n,text):return(n.lineno-1,n.end_lineno,textwrap.indent(textwrap.dedent(text).strip()+'\n',' '*n.col_offset))
def no_scroll(s,idx):
 changes=[]
 for _,c in idx.indexed_nodes_of_type(ast.ClassDef):
  if c.name=='CheckboxValueState':changes.append(whole(c,''));continue
  if c.name=='NoScrollComboBox':
   for n in c.body:
    if isinstance(n,ast.FunctionDef)and n.name in {'get_value','set_value'}:changes.append(whole(n,''))
  if c.name!='NoneAwareCheckBox':continue
  for n in c.body:
   if not isinstance(n,ast.FunctionDef):continue
   if n.name in {'connect_change_signal','disconnect_change_signal'}:changes.append(whole(n,''))
   elif n.name=='get_value':changes.append(whole(n,'''def _read_concrete_value(self):
    return self.isChecked()
'''))
   elif n.name=='set_value':changes.append(whole(n,'''def _write_concrete_value(self, value):
    self.setChecked(bool(value))

def _signal_sources(self):
    return ((self, self.stateChanged),)

def _apply_draft_style(self):
    if self.has_placeholder_state():
        self._apply_placeholder_palette()
    else:
        self._apply_concrete_palette()
'''))
   elif n.name=='is_placeholder':changes.append(whole(n,'''def is_placeholder(self):
    return self.has_placeholder_state()
'''))
   elif n.name=='convert_placeholder_to_concrete':changes.append(whole(n,'''def convert_placeholder_to_concrete(self):
    self.clear_placeholder_state()
    self._apply_draft_style()
'''))
 for _,n in idx.indexed_nodes_of_type(ast.Assign):
  if 'CheckboxValueState.' in ast.unparse(n):changes.append(whole(n,''))
 return changes
transform(ROOT/'widgets/no_scroll_spinbox.py',no_scroll)
def text_owner(s,idx):
 changes=[];lines=s.splitlines(keepends=True)
 for _,c in idx.indexed_nodes_of_type(ast.ClassDef):
  if c.name=='NoneAwareTextValueMixin':
   header=lines[c.lineno-1].replace('(DebouncedTextSignalMixin)', '(DebouncedTextSignalMixin, PlaceholderStateMixin)');changes.append((c.lineno-1,c.lineno,header))
   for n in c.body:
    if isinstance(n,ast.FunctionDef)and n.name=='set_value':
     original=''.join(lines[n.lineno-1:n.end_lineno]).replace('def set_value(', 'def _write_concrete_value(',1)
     changes.append((n.lineno-1,n.end_lineno,original))
   changes.append((c.end_lineno,c.end_lineno,'\n    def _signal_sources(self):\n        return ((self, self.textChanged),)\n'))
  if any(ast.unparse(base) == 'NoneAwareTextValueMixin' for base in c.bases):
   for n in c.body:
    if not isinstance(n,ast.FunctionDef):continue
    if n.name=='get_value':
     original=''.join(lines[n.lineno-1:n.end_lineno]).replace('def get_value(', 'def _read_concrete_value(',1)
     if c.name=='NoneAwareLineEdit':original=' '*n.col_offset+'def _read_concrete_value(self):\n'+' '*(n.col_offset+4)+'return self.text().strip()\n'
     changes.append((n.lineno-1,n.end_lineno,original))
    if n.name=='set_value' and c.name=='TypedLiteralContainerEdit':
     original=''.join(lines[n.lineno-1:n.end_lineno]);body=original.splitlines(keepends=True)
     body.insert(1,' '*(n.col_offset+4)+'if not FieldValue.of(value).has_value:\n'+' '*(n.col_offset+8)+'super().set_value(value)\n'+' '*(n.col_offset+8)+'return\n')
     changes.append((n.lineno-1,n.end_lineno,''.join(body)))
 return changes
transform(ROOT/'forms/widget_strategies.py',text_owner)
p=ROOT/'forms/widget_strategies.py';s=p.read_text();s=s.replace('from objectstate import ', 'from objectstate.field_value import FieldValue\nfrom objectstate import ',1);p.write_text(s)
# Names describe the capability, not the domain null value that used to request it.
for root in [ROOT,Path('/home/ts/wt/openhcs-declared-fields/openhcs'),Path('/home/ts/wt/formbridge-declared-fields/src')]:
 for p in root.rglob('*.py'):
  s=p.read_text();new=s.replace('NoneAwareCheckBox','InheritedCheckBox').replace('NoneAwareTextValueMixin','FieldTextValueMixin').replace('NoneAwareLineEdit','InheritedLineEdit').replace('NoneAwareIntEdit','InheritedIntEdit')
  if new!=s:ast.parse(new,filename=str(p));p.write_text(new)
