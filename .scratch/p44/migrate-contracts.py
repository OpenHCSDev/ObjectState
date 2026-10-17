import ast,tokenize,io
from pathlib import Path
root=Path('/home/ts/wt/objectstate-declared-fields')
p=root/'tests/test_subfield_semantics.py';s=p.read_text();tree=ast.parse(s);lines=s.splitlines(keepends=True);starts=[0]
for line in lines:starts.append(starts[-1]+len(line))
edits=[]
for node in ast.walk(tree):
 if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='state':
  method=node.func.attr
  if method in ('update_parameter','get_resolved_value'):
   path=ast.get_source_segment(s,node.args[0]);field=f'DottedFieldPath({path}).bind(state)'
   replacement=field+'.value' if method=='get_resolved_value' else field+'.write('+ast.get_source_segment(s,node.args[1])+')'
   edits.append((starts[node.lineno-1]+node.col_offset,starts[node.end_lineno-1]+node.end_col_offset,replacement))
for a,b,v in sorted(edits,reverse=True):s=s[:a]+v+s[b:]
s=s.replace('state.on_resolved_changed(', 'state._listen_resolved(').replace('state.on_state_changed(', 'state._listen_state(').replace('state.parameters["bindings"]','state.fields.bindings.raw')
p.write_text(s)
for name in ('test_integration.py','test_lazy_factory.py','test_lazy_counterpart_registry.py'):
 p=root/'tests'/name;s=p.read_text();tree=ast.parse(s);lines=s.splitlines(keepends=True);starts=[0]
 for line in lines:starts.append(starts[-1]+len(line))
 for node in reversed(tree.body):
  if isinstance(node,ast.ImportFrom) and node.module=='objectstate' and any(a.name=='get_base_type_for_lazy' for a in node.names):
   node.names=[a for a in node.names if a.name!='get_base_type_for_lazy']
   a=starts[node.lineno-1]+node.col_offset;b=starts[node.end_lineno-1]+node.end_col_offset
   s=s[:a]+'from python_introspect import resolve_declared_type\n'+ast.unparse(node)+s[b:]
 tokens=[t._replace(string='resolve_declared_type') if t.type==tokenize.NAME and t.string=='get_base_type_for_lazy' else t for t in tokenize.generate_tokens(io.StringIO(s).readline)]
 s=tokenize.untokenize(tokens).replace('resolve_declared_type(Unregistered) is None','get_lazy_type_for_base(Unregistered) is None')
 p.write_text(s)
