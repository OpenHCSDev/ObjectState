"""Port the eight source-adjudicated DTO fixture constructors, not arbitrary nulls."""
import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
root=Path('/home/ts/wt/openhcs-declared-fields/tests/unit/agent')
records=[]
for filename in ('test_mcp_server.py','test_mcp_dev_client_knowledge_renderers.py','test_object_state_field_help_service.py','test_ui_bridge_service.py'):
 p=root/filename;s=p.read_text();module=SourceModule.from_source_path(p,s).parse().module;syntax=module_syntax_index(module)
 starts=[0]
 for line in s.splitlines(keepends=True): starts.append(starts[-1]+len(line))
 def pos(line,col):
  text=s[starts[line-1]:starts[line]];return starts[line-1]+len(text.encode()[:col].decode())
 edits=[]
 for _,n in syntax.indexed_nodes_of_type(ast.Call):
  if not isinstance(n.func,ast.Name) or n.func.id not in {'UiObjectStateFieldSummary','UiObjectStateFieldProjection','UiWidgetActionSummary'}:continue
  ks={k.arg:k for k in n.keywords}; changed=[]
  inherited=ast.unparse(ks['inherited_value'].value) if 'inherited_value' in ks else 'False'
  for key in ('raw_value','resolved_value'):
   if key not in ks:continue
   node=ks[key].value; old=s[pos(node.lineno,node.col_offset):pos(node.end_lineno,node.end_col_offset)]
   replacement='Inherit()' if key=='raw_value' and inherited=='True' and old=='None' else f'Value({old})'
   edits.append((pos(node.lineno,node.col_offset),pos(node.end_lineno,node.end_col_offset),replacement));changed.append(key)
  for key in ('raw_value_is_none','resolved_value_is_none'):
   if key not in ks:continue
   node=ks[key]; value=ast.unparse(node.value); replacement=''
   target='raw_value' if key.startswith('raw_') else 'resolved_value'
   indent=' '*node.col_offset
   if target not in ks and value=='True':
    meaning='Inherit()' if target=='raw_value' and inherited=='True' else 'Value(None)'
    replacement=f'{indent}{target}={meaning},\n'
   elif target=='raw_value' and value=='inherited_value':
    replacement=f'{indent}raw_value=Inherit() if inherited_value else Value(False),\n'
   elif value not in ('True','False'):raise RuntimeError(f'OPEN fixture {p}:{node.lineno}: {value}')
   if node.lineno!=node.end_lineno:raise RuntimeError('Expected adjudicated single-line flag')
   edits.append((starts[node.lineno-1],starts[node.lineno],replacement)); changed.append(key)
  if changed:records.append((str(p),n.lineno,n.func.id,changed))
 if edits:
  future=[node.end_lineno for node in module.body if isinstance(node,ast.ImportFrom) and node.module=='__future__']
  after=max(future,default=(module.body[0].end_lineno if isinstance(module.body[0],ast.Expr) and isinstance(module.body[0].value,ast.Constant) and isinstance(module.body[0].value.value,str) else 0))
  edits.append((starts[after],starts[after],'from objectstate.field_value import Inherit, Unset, Value\n'))
  for a,b,text in sorted(edits,reverse=True):s=s[:a]+text+s[b:]
  compile(s,str(p),'exec');p.write_text(s)
print(json.dumps(records,indent=2))
