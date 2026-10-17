import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate')
for p in ROOT.glob('*.py'):
 s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);offsets=[];at=0
 for line in lines:offsets.append(at);at+=len(line)
 edits=[]
 for _,n in idx.indexed_nodes_of_type(ast.Attribute):
  if n.attr=='parameters'and isinstance(n.value,ast.Name)and n.value.id in {'state','schema'}:
   a=offsets[n.lineno-1]+len(lines[n.lineno-1].encode()[:n.col_offset].decode());b=offsets[n.end_lineno-1]+len(lines[n.end_lineno-1].encode()[:n.end_col_offset].decode());edits.append((a,b,ast.unparse(n.value)+'._parameters'))
 for a,b,t in sorted(edits,reverse=True):s=s[:a]+t+s[b:]
 compile(s,str(p),'exec');p.write_text(s)
p=ROOT/'object_state_registry.py';s=p.read_text();s=s.replace('pipeline_state.update_parameter("step_scope_ids", new_ids)','pipeline_state.fields.step_scope_ids.write(new_ids)');compile(s,str(p),'exec');p.write_text(s)
p=ROOT/'inspection.py';s=p.read_text();s=s.replace('''    def of(cls, state: ObjectState, field_path: str):
        """Inspect ``field_path``; a value that fails to resolve is reported unavailable."""
''','''    def of(cls, field):
        """Capture one admitted field, never look up a caller-spelled path."""
        state = field.state
        field_path = field._path
''').replace('state.get_resolved_value(field_path)','field.value').replace('raw_value=state._parameters[field_path]','raw_value=field.raw');compile(s,str(p),'exec');p.write_text(s)
p=ROOT/'edit_session.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
 if n.name in {'has_parameter','parameter_value','update_parameter'}:edits.append((n.lineno-1,n.end_lineno,''))
 if n.name=='require_state':edits.append((n.lineno-1,n.end_lineno,'''    def require_state(self) -> ObjectState:
        state = self.state
        if state is None:
            raise RuntimeError("ObjectStateEditSession has no editing state")
        return state
'''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines).rstrip()+'\n';compile(s,str(p),'exec');p.write_text(s)
