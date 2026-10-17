import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
roots=[Path('/home/ts/wt/'+name+'-declared-fields') for name in ('objectstate','formbridge','pyqt','openhcs','toad')]
rows=[]
for root in roots:
 for p in (root/'tests').rglob('*.py'):
  s=p.read_text();syntax=module_syntax_index(SourceModule.from_source_path(p,s).parse().module)
  for _,n in syntax.indexed_nodes_of_type(ast.Call):
   ks={k.arg:ast.unparse(k.value) for k in n.keywords if k.arg in {'raw_value','resolved_value','raw_value_is_none','resolved_value_is_none'}}
   if ks: rows.append((str(p),n.lineno,ast.unparse(n.func),ks))
print(json.dumps(rows,indent=2))
