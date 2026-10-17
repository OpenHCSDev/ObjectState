"""Project UI/log addresses from the admitted field; keep no path mirrors."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/services/field_change_dispatcher.py');s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module)
lines=s.splitlines(keepends=True);offsets=[];at=0
for line in lines:offsets.append(at);at+=len(line)
edits=[]
for _,n in idx.indexed_nodes_of_type(ast.Attribute):
 if not isinstance(n.value,ast.Name)or n.value.id!='context':continue
 target={'source':'context.event.source_manager','source_path':'context.field.address.value','root_path':'context.field.address.value'}.get(n.attr)
 if target is None:continue
 a=offsets[n.lineno-1]+len(lines[n.lineno-1].encode()[:n.col_offset].decode());b=offsets[n.end_lineno-1]+len(lines[n.end_lineno-1].encode()[:n.end_col_offset].decode());edits.append((a,b,target))
for a,b,t in sorted(edits,reverse=True):s=s[:a]+t+s[b:]
compile(s,str(p),'exec');p.write_text(s)
