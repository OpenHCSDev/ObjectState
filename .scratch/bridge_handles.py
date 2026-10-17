import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/formbridge-declared-fields/src/formbridge/bridge/object_state.py');s=P.read_text();s=s.replace('from objectstate.inspection import FieldInspection, type_name, type_qualname','from objectstate.inspection import FieldInspection, type_name, type_qualname\nfrom objectstate.field_access import DottedFieldPath, FieldAccessError')
s=s.replace('parameter_count=len(state.parameters)','parameter_count=len(state.fields)')
idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
for _,c in idx.indexed_nodes_of_type(ast.ClassDef):
 for n in c.body:
  if not isinstance(n,ast.FunctionDef):continue
  old=''.join(lines[n.lineno-1:n.end_lineno]);new=None
  if c.name=='ObjectStateFieldMutationService':
   if n.name=='_field_summary':new=''
   if n.name=='_converted_value':new='''    @staticmethod
    def _converted_value(field, value):
        return ParameterFormService().convert_value_to_type(
            value, field.annotation, field.name, field.declaring_type,
        )
'''
   if n.name=='mutate':
    new=old.replace('''        if request.field_path not in state.parameters:
''','''        try:
            field = DottedFieldPath(request.field_path).bind(state)
        except FieldAccessError:
''')
    new=new.replace('before = self._field_summary(state, request)','before = ObjectStateFieldSemanticProjection.of(field).to_field_summary(include_values=request.include_field_values)')
    new=new.replace('state.reset_parameter(request.field_path)','field.reset()')
    new=new.replace('''state.update_parameter(
                    request.field_path,
                    self._converted_value(state, request),
                )''','''field.write(self._converted_value(field, request.value))''')
    new=new.replace('after = self._field_summary(state, request)','after = ObjectStateFieldSemanticProjection.of(field).to_field_summary(include_values=request.include_field_values)')
  elif n.name=='_field_page':
   a=old.index('        if request.field_paths:');b=old.index('        if request.field_filter',a)
   new=old[:a]+'''        available = tuple(state.fields)
        if request.field_paths:
            all_field_paths = tuple(item for item in available if item.address.value in request.field_paths)
        else:
            all_field_paths = tuple(sorted(available, key=lambda item: item.address.value))
'''+old[b:]
   new=new.replace('''                        state,
                        field_path,''','''                        field_path,''').replace('''                state,
                field_path,''','''                field_path,''')
   new=new.replace('''self._field_summary(
                        field_path,''','''ObjectStateFieldSemanticProjection.of(field_path).to_field_summary(''').replace('''self._field_summary(
                field_path,''','''ObjectStateFieldSemanticProjection.of(field_path).to_field_summary(''')
  elif n.name=='_field_summary':
   new=''
  if new is not None:
   start=min([n.lineno]+[d.lineno for d in n.decorator_list])-1
   edits.append((start,n.end_lineno,new+'\n'if new else''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines);compile(s,str(P),'exec');P.write_text(s)
