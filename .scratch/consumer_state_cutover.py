import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
changes={
'/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/services/widget_service.py':{
'_apply_context_behavior': [('if value is None:', 'if FieldValue.of(value).inherited:'),('elif value is not None:', 'else:')]},
'/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/services/parameter_ops_service.py':{
'_reset_value_widget_parameter':[('if reset_value is None:', 'if FieldValue.of(reset_value).inherited:')],
'refresh_single_placeholder':[('if current_value is not None:', 'if not FieldValue.of(current_value).inherited:')]},
'/home/ts/wt/formbridge-declared-fields/src/formbridge/forms/parameter_form_service.py':{
'get_reset_value_for_parameter':None,'_get_actual_dataclass_field_default':None},
}
for name,methods in changes.items():
 p=Path(name);s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
 for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
  if n.name not in methods:continue
  pairs=methods[n.name];text=''.join(lines[n.lineno-1:n.end_lineno])if pairs is not None else''
  for old,new in pairs or []:
   assert old in text,(p,n.name,old);text=text.replace(old,new)
  edits.append((n.lineno-1,n.end_lineno,text))
 for a,b,text in sorted(edits,reverse=True):lines[a:b]=[text]
 s=''.join(lines)
 if any(v is not None for v in methods.values()):s='from objectstate.field_value import FieldValue\n'+s
 ast.parse(s,filename=str(p));p.write_text(s)
