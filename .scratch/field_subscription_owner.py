import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py');s=P.read_text();idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
for _,c in idx.indexed_nodes_of_type(ast.ClassDef):
 if c.name not in {'FieldProxy','RootFields'}:continue
 for n in c.body:
  if not isinstance(n,ast.FunctionDef)or n.name!='subscribe':continue
  if c.name=='FieldProxy':text='''    def _notify_subscriber(self, callback, paths):
        owner = DottedFieldPath(self._path)
        selected = [path for path in paths if owner.contains_path(path)]
        if selected:
            callback(frozenset(self._state._field_at(path) for path in selected if path in self._state._parameter_structure.declarations))

    def _subscribe(self, callback, listen, unlisten):
        def changed(paths):
            self._notify_subscriber(callback, paths)
        listen(changed)
        def release():
            unlisten(changed)
        return release

    def subscribe(self, callback):
        """Observe this field's state; receive changed field handles, never strings."""
        return self._subscribe(callback, self._state._listen_state, self._state._unlisten_state)

    def subscribe_value(self, callback):
        """Observe resolved-value changes, including changes inherited from elsewhere."""
        return self._subscribe(callback, self._state._listen_resolved, self._state._unlisten_resolved)
'''
  else:text='''    def _notify_subscriber(self, callback, paths):
        callback(frozenset(self._state._field_at(path) for path in paths if path in self._structure.declarations))
'''
  edits.append((n.lineno-1,n.end_lineno,text))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines);compile(s,str(P),'exec');P.write_text(s)
