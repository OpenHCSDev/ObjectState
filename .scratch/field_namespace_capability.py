"""A root namespace is not a declared field: share only the actual capability."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py');s=P.read_text();idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True)
classes={c.name:c for _,c in idx.indexed_nodes_of_type(ast.ClassDef)}
leaf=classes['FieldProxy'];root=classes['RootFields'];shared={'state','_structure','children','__getattr__','_subscribe','subscribe','subscribe_value'};methods=[];edits=[]
for n in leaf.body:
 if isinstance(n,ast.FunctionDef)and n.name in shared:
  a=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;b=n.end_lineno
  methods.append(''.join(lines[a:b]));edits.append((a,b,''))
capability='''class FieldNamespace:
    """Declaration discovery and observer lifetime shared by roots and fields.

    A namespace promises neither a field default nor a writable datum. Each
    concrete scope owns its admission check and changed-field projection.
    """
'''+ '\n'.join(methods)+'\n\n'
edits.append((leaf.lineno-1,leaf.lineno-1,capability))
for n in root.body:
 if isinstance(n,ast.FunctionDef)and n.name in {'raw','value','write','reset','present'}:
  a=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;b=n.end_lineno
  edits.append((a,b,''))
edits.append((root.end_lineno,root.end_lineno,'''
    def _require_present(self):
        self._state._check_and_sync_delegate()
'''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines).replace('class FieldProxy:', 'class FieldProxy(FieldNamespace):').replace('class RootFields(FieldProxy):','class RootFields(FieldNamespace):')
compile(s,str(P),'exec');P.write_text(s)
