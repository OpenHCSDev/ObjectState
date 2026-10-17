"""Owned source evidence for ObjectState #32/#46, using NRA's syntax/family owners."""
import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
from nominal_refactor_advisor.class_index import build_class_family_index
ROOTS=[Path('/home/ts/wt/objectstate-declared-fields/src/objectstate'),Path('/home/ts/wt/openhcs-declared-fields/openhcs'),Path('/home/ts/wt/core-doctrine-segment/src/agent_comms'),Path('/home/ts/wt/toad-declared-fields/src/toad'),Path('/home/ts/wt/formbridge-declared-fields/src/formbridge'),Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive'),Path('/home/ts/wt/python-introspect-field-values/src/python_introspect'),Path('/home/ts/code/projects/openhcs/external/pycodify/src/pycodify')]
modules=[];original=[];sites=[];errors=[]
for root in ROOTS:
 for path in root.rglob('*.py'):
  try: parsed=SourceModule.from_source_path(path,path.read_text()).parse()
  except Exception as e:errors.append((str(path),str(e)));continue
  modules.append(parsed);syntax=module_syntax_index(parsed.module)
  for _,node in syntax.indexed_nodes_of_type(ast.ClassDef):
   original.append((str(path),node.lineno,node.name,[ast.unparse(b)for b in node.bases]))
  for _,node in syntax.indexed_nodes_of_type(ast.Call):
   name=ast.unparse(node.func)
   if any(s in name for s in ('update_parameter','reset_parameter','get_resolved_value','on_state_changed','on_resolved_changed','patch_lazy_constructors','global_pipeline_config','rebuild_with_none','_reconstruct_from','reconstruct_top_level_parameters','type_for_path','FieldProxy','FieldInspection','DottedFieldPath','set_placeholder','setSpecialValueText','_write_concrete_value','_write_blank_value')):
    sites.append((str(path),node.lineno,'call',ast.unparse(node)))
  relevant={'parameters','_parameters','_parameter_structure','declarations','direct_paths','owner_paths','dirty_fields','signature_diff_fields','raw_value','raw_value_is_none','resolved_value_is_none','raw_value_preview','resolved_value_preview','resolved_value','resolved_value_available','resolved','_draft','_write_concrete_value','_write_blank_value','setSpecialValueText','has_value','is_none','_on_state_changed_callbacks','_on_resolved_changed_callbacks'}
  for _,node in syntax.indexed_nodes_of_type(ast.Attribute):
   if node.attr in relevant:sites.append((str(path),node.lineno,type(node.ctx).__name__,ast.unparse(node)))
  for _,node in syntax.indexed_nodes_of_type(ast.ImportFrom):
   if (node.module or '').startswith(('objectstate','pycodify','python_introspect')):sites.append((str(path),node.lineno,'import',ast.unparse(node)))
  if root.name=='objectstate' or path.name=='widget_adapters.py':
   for _,node in syntax.indexed_nodes_of_type(ast.Compare):
    if any(isinstance(n,ast.Constant)and n.value is None for n in node.comparators):sites.append((str(path),node.lineno,'None decision',ast.unparse(node)))
index=build_class_family_index(modules)
print(json.dumps({'roots':list(map(str,ROOTS)),'module_count':len(modules),'original_classes':original,'sites':sites,'parse_errors':errors,'index_type':type(index).__name__,'index_members':[n for n in dir(index)if n in ('classes_by_symbol','classes','symbols_by_simple_name')]},indent=2))
