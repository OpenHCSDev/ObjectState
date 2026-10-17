"""Current production decisions and DTO declaration fields, through NRA syntax."""
import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
roots=[Path('/home/ts/wt/objectstate-declared-fields/src'),Path('/home/ts/wt/formbridge-declared-fields/src')]
rows=[];fields=[];errors=[];counts={}
for root in roots:
 for p in root.rglob('*.py'):
  try: module=SourceModule.from_source_path(p,p.read_text()).parse().module
  except Exception as e: errors.append((str(p),str(e)));continue
  syntax=module_syntax_index(module)
  for _,n in syntax.indexed_nodes_of_type(ast.Call):
   name=n.func.id if isinstance(n.func,ast.Name) else n.func.attr if isinstance(n.func,ast.Attribute) else ''
   if name in {'is_container','is_config_type','is_dataclass','getattr'}:
    rows.append((str(p),n.lineno,name,ast.unparse(n)))
    counts.setdefault(root.parent.name,{}).setdefault(name,0);counts[root.parent.name][name]+=1
  for _,n in syntax.indexed_nodes_of_type(ast.AnnAssign):
   if isinstance(n.target,ast.Name) and n.target.id.endswith('_type'):
    fields.append((str(p),n.lineno,n.target.id,ast.unparse(n.annotation)))
print(json.dumps({'counts':counts,'calls':rows,'type_fields':fields,'parse_errors':errors},indent=2))
