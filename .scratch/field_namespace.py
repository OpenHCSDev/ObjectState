import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py');s=P.read_text();idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
c=next(c for _,c in idx.indexed_nodes_of_type(ast.ClassDef)if c.name=='RootFields')
text='''class RootFields(FieldProxy):
    """The live root namespace shares field discovery, not a captured schema."""
    def __init__(self, state):
        self._state = state

    @property
    def _structure(self):
        return self._state._parameter_structure

    @property
    def _path(self):
        return ''

    @property
    def present(self):
        return True

    @property
    def raw(self):
        return self._state.to_object()

    @property
    def value(self):
        return self._state.to_resolved_object()

    def write(self, value):
        return self._state.update_object_instance(value)

    def reset(self):
        return self._state.reset_all_parameters()

    def __iter__(self):
        self._state._check_and_sync_delegate()
        return iter(tuple(self._state._field_at(path) for path in self._structure.declarations))

    def bind(self, owner, names, field_type=FieldProxy):
        """Bind an already declared attribute vector to this editing state."""
        target = self._state._extraction_target
        if not ((isinstance(owner, type) and isinstance(target, owner)) or target is owner):
            raise FieldAccessError(f"{owner!r} does not declare this editing target")
        if isinstance(names, str) or not names:
            raise TypeError("Binding requires declared attribute segments, not a dotted string")
        path = DottedFieldPath('')
        for name in names:
            candidates = self._structure.direct_paths.get(path, ())
            path = next((child for child in candidates if child.field_name == name), None)
            if path is None:
                raise FieldAccessError(f"No declared field segment {name!r}")
        return field_type(self._state, path.value)

    def subscribe(self, callback):
        def changed(paths):
            callback(frozenset(self._state._field_at(path) for path in paths if path in self._structure.declarations))
        self._state._listen_state(changed)
        def release():
            self._state._unlisten_state(changed)
        return release
'''
edits.append((c.lineno-1,c.end_lineno,text+'\n'))
c=next(c for _,c in idx.indexed_nodes_of_type(ast.ClassDef)if c.name=='FieldProxy')
for n in c.body:
 if not isinstance(n,ast.FunctionDef):continue
 if n.name=='__getattr__':edits.append((n.lineno-1,n.end_lineno,'''    def __getattr__(self, name):
        self._require_present()
        for child in self._structure.direct_paths.get(DottedFieldPath(self._path), ()):
            if child.field_name == name:
                return self._state._field_at(child.value)
        raise AttributeError(f"Field {self._path!r} has no declared child {name!r}")
'''))
 if n.name=='_require_present':edits.append((n.lineno-1,n.end_lineno,'''    def _require_present(self):
        self._state._check_and_sync_delegate()
        if not self.present:
            raise FieldAccessError(f"Field {self._path!r} belongs to a retired declaration")
'''))
edits.append((c.end_lineno,c.end_lineno,'''
    @property
    def address(self):
        """The existing address codec owns display/wire spelling, not callers."""
        return DottedFieldPath(self._path)

    def inspect(self):
        from objectstate.inspection import FieldInspection
        return FieldInspection.of(self)
'''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines);compile(s,str(P),'exec');P.write_text(s)
