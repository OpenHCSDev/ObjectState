"""Replace source-enumerated FieldValue flags with member behavior using NRA."""
import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
roots=[Path('/home/ts/wt/'+name+'-declared-fields/src') for name in ('objectstate','formbridge','pyqt','toad')]
records=[]
for root in roots:
 for p in root.rglob('*.py'):
  s=p.read_text();syntax=module_syntax_index(SourceModule.from_source_path(p,s).parse().module)
  starts=[0]
  for line in s.splitlines(keepends=True):starts.append(starts[-1]+len(line))
  def pos(line,col):
   text=s[starts[line-1]:starts[line]];return starts[line-1]+len(text.encode()[:col].decode())
  edits=[]
  for _,n in syntax.indexed_nodes_of_type(ast.Attribute):
   if n.attr not in {'has_value','inherited'}:continue
   receiver=ast.unparse(n.value)
   admitted=receiver.startswith('FieldValue.of(') or receiver in {'self._draft','draft','self.resolved'}
   if not admitted:raise RuntimeError(f'OPEN receiver: {p}:{n.lineno}: {ast.unparse(n)}')
   if n.attr=='has_value':replacement=f'{receiver}.available()'
   else:
    if isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='FieldValue.of':replacement=f'FieldValue.is_inherited({ast.unparse(n.value.args[0])})'
    else:replacement=f'FieldValue.is_inherited({receiver})'
   edits.append((pos(n.lineno,n.col_offset),pos(n.end_lineno,n.end_col_offset),replacement))
   records.append((str(p),n.lineno,ast.unparse(n),replacement))
  for a,b,t in sorted(edits,reverse=True):s=s[:a]+t+s[b:]
  if edits:compile(s,str(p),'exec');p.write_text(s)
print(json.dumps(records,indent=2))
