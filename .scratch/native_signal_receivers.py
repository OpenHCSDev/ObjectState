"""NRA-selected native signal declarations include their receiver, not sender guesses."""
import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
rows=[]
for p in Path('/home/ts/wt/pyqt-declared-fields/src').rglob('*.py'):
 s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);starts=[0]
 for line in lines:starts.append(starts[-1]+len(line))
 def pos(line,col):return starts[line-1]+len(lines[line-1].encode()[:col].decode())
 methods=[n for _,n in idx.indexed_nodes_of_type(ast.FunctionDef) if n.name=='_signal_sources'];edits=[]
 for method in methods:
  for _,n in idx.indexed_nodes_of_type(ast.Tuple):
   if method.lineno<n.lineno<=method.end_lineno and len(n.elts)==2 and not isinstance(n.elts[0],ast.Tuple):
    edits.append((pos(n.lineno,n.col_offset),pos(n.end_lineno,n.end_col_offset),f'({ast.unparse(n.elts[0])}, {ast.unparse(n.elts[1])}, self._native_input)'));rows.append((str(p),n.lineno))
 for a,b,t in sorted(edits,reverse=True):s=s[:a]+t+s[b:]
 if edits:compile(s,str(p),'exec');p.write_text(s)
print(json.dumps(rows,indent=2))
