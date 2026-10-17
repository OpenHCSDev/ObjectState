"""Port actual ObjectState field operations, not similarly named UI operations.

NRA indexes source; admission remains DottedFieldPath/FieldProxy's work.
The state receiver set is source-adjudicated, not a dynamic binding proof.
"""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index
ROOT=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive')
owner=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py')
owner_index=module_syntax_index(SourceModule.from_source_path(owner,owner.read_text()).parse().module)
RESERVED={n.name for _,c in owner_index.indexed_nodes_of_type(ast.ClassDef) if c.name in {'FieldNamespace','FieldProxy','RootFields'} for n in c.body if isinstance(n,ast.FunctionDef)}
OPS={'get_resolved_value':'value','get_saved_resolved_value':'saved_value','signature_default':'default','update_parameter':'write','reset_parameter':'reset','get_provenance':'inspect().provenance'}
def state_expr(n):
 s=ast.unparse(n)
 return s in {'state','func_state','self._state','self._subscribed_state'} or s.endswith('.state')
def field(state,path):
 if isinstance(path,ast.Constant)and isinstance(path.value,str)and all(p.isidentifier()for p in path.value.split('.')) and not any(p in RESERVED for p in path.value.split('.')):
  # Namespace traversal is declaration admission, not string-based data access.
  return f'{ast.unparse(state)}.fields.{path.value}'
 return f'DottedFieldPath({ast.unparse(path)}).bind({ast.unparse(state)})'
for p in ROOT.rglob('*.py'):
 s=p.read_text();changed=False
 for stage in ('subscript','call'):
  idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);offsets=[];at=0
  for line in lines:offsets.append(at);at+=len(line)
  edits=[]
  def add(n,text):
   a=offsets[n.lineno-1]+len(lines[n.lineno-1].encode()[:n.col_offset].decode());b=offsets[n.end_lineno-1]+len(lines[n.end_lineno-1].encode()[:n.end_col_offset].decode());edits.append((a,b,text))
  if stage=='subscript':
   for _,n in idx.indexed_nodes_of_type(ast.Subscript):
    if isinstance(n.ctx,ast.Load)and isinstance(n.value,ast.Attribute)and n.value.attr=='parameters'and state_expr(n.value.value):add(n,field(n.value.value,n.slice)+'.raw')
  else:
   for _,n in idx.indexed_nodes_of_type(ast.Call):
    if not isinstance(n.func,ast.Attribute):continue
    f=n.func
    if f.attr in OPS and state_expr(f.value):
     assert n.args and not n.keywords,(p,n.lineno,ast.unparse(n))
     bound=field(f.value,n.args[0]);op=OPS[f.attr]
     if op in {'write','reset'}:text=f'{bound}.{op}('+', '.join(ast.unparse(a)for a in n.args[1:])+')'
     else:text=f'{bound}.{op}'
     add(n,text)
    elif f.attr=='get'and isinstance(f.value,ast.Attribute)and f.value.attr=='parameters'and state_expr(f.value.value):
     assert n.args and not n.keywords,(p,n.lineno)
     if len(n.args)>1:
      print('OPEN explicit missing-declaration policy',p,n.lineno,ast.unparse(n));continue
     add(n,field(f.value.value,n.args[0])+'.raw')
  # An outer operation would need to consume the already rewritten inner input.
  # Keep that uncertainty visible instead of applying overlapping edits.
  ordered=sorted(edits)
  assert all(a[1]<=b[0]for a,b in zip(ordered,ordered[1:])),(p,'overlapping source operations')
  for a,b,t in reversed(ordered):s=s[:a]+t+s[b:]
  changed|=bool(edits)
 if not changed:continue
 if 'DottedFieldPath('in s:
  tree=SourceModule.from_source_path(p,s).parse().module
  top=[n for n in tree.body if isinstance(n,ast.ImportFrom)]
  if not any(n.module in {'objectstate','objectstate.field_access'}and any(a.name=='DottedFieldPath'and a.asname is None for a in n.names)for n in top):
   lines=s.splitlines(keepends=True);future=[n.end_lineno for n in top if n.module=='__future__'];at=max(future,default=0)
   if not at and tree.body and isinstance(tree.body[0],ast.Expr)and isinstance(tree.body[0].value,ast.Constant)and isinstance(tree.body[0].value.value,str):at=tree.body[0].end_lineno
   lines[at:at]=['\nfrom objectstate import DottedFieldPath\n'];s=''.join(lines)
 compile(s,str(p),'exec');p.write_text(s);print(p.relative_to(ROOT))
