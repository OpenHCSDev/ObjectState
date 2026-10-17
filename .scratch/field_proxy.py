"""Declaration-owned live field handles; no caller-built dotted path API."""
import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py')
s=P.read_text().replace('from objectstate.field_access import DataclassFieldAccess, DottedFieldPath', 'from objectstate.field_access import DataclassFieldAccess, DottedFieldPath, FieldAccessError');idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module)
n=next(n for _,n in idx.indexed_nodes_of_type(ast.ClassDef)if n.name=='FieldProxy')
source='''class FieldProxy:
    """One declaration bound to an editing state.

    The structure, not dataclass reflection repeated by each consumer, admits the
    field. The handle owns its reads, reset and subscriptions; ObjectState owns
    the complete mutation/invalidation transaction.
    """
    def __init__(self, state: 'ObjectState', path: str):
        state._check_and_sync_delegate()
        if path not in state._parameter_structure.declarations:
            raise FieldAccessError(f"No declared field {path!r} on {type(state.saved_object).__name__}")
        self._state = state
        self._path = path
        self._structure = state._parameter_structure

    @property
    def state(self):
        return self._state

    @property
    def declaration(self):
        return self._structure.declarations[self._path]

    @property
    def name(self):
        return self.declaration.name

    @property
    def annotation(self):
        return self.declaration.param_type

    @property
    def default(self):
        return self.declaration.default_value

    @property
    def description(self):
        return self.declaration.description

    @property
    def declaring_type(self):
        return self._structure.owner_paths[self._path]

    @property
    def present(self):
        return self._structure is self._state._parameter_structure and self._path in self._state._parameters

    def _require_present(self):
        if not self.present:
            raise FieldAccessError(f"Field {self._path!r} belongs to a retired declaration")

    @property
    def raw(self):
        self._require_present()
        return self._state._parameters[self._path]

    @property
    def value(self):
        self._require_present()
        return self._state._read_field(self)

    @property
    def saved_value(self):
        return self._state._read_saved_field(self)

    @property
    def dirty(self):
        self._state._ensure_live_resolved()
        return self._path in self._state._dirty_fields

    @property
    def signature_diff(self):
        return self.raw != self.default

    def write(self, value):
        self._require_present()
        return self._state._write_field(self, value)

    def reset(self):
        from copy import deepcopy
        return self.write(deepcopy(self.default))

    @property
    def children(self):
        self._require_present()
        return tuple(self._state._field_at(path.value) for path in self._structure.direct_paths.get(DottedFieldPath(self._path), ()))

    def __getattr__(self, name):
        for child in self.children:
            if child.name == name:
                return child
        raise AttributeError(f"Field {self._path!r} has no declared child {name!r}")

    def subscribe(self, callback):
        """Call a field observer without making it compare path strings.

        Return the one registration's release operation, for the view's existing
        resource lifetime. Container observers also see their descendants.
        """
        path = DottedFieldPath(self._path)
        def changed(paths):
            if path.contains_any(paths):
                callback()
        self._state._listen_state(changed)
        def release():
            self._state._unlisten_state(changed)
        return release

    def __eq__(self, other):
        return isinstance(other, FieldProxy) and self._state is other._state and self._structure is other._structure and self._path == other._path

    def __hash__(self):
        return hash((id(self._state), id(self._structure), self._path))

    def __repr__(self):
        return f"{type(self).__name__}({self._path!r})"


class RootFields:
    """A state's declaration namespace survives replacement of its schema."""
    def __init__(self, state):
        self._state = state

    @property
    def children(self):
        structure = self._state._parameter_structure
        return tuple(self._state._field_at(path.value) for path in structure.direct_paths.get(DottedFieldPath(''), ()))

    def __iter__(self):
        return iter(tuple(self._state._field_at(path) for path in self._state._parameter_structure.declarations))

    def __getattr__(self, name):
        for child in self.children:
            if child.name == name:
                return child
        raise AttributeError(f"No declared root field {name!r}")

    def subscribe(self, callback):
        def changed(paths):
            callback(frozenset(self._state._field_at(path) for path in paths if path in self._state._parameter_structure.declarations))
        self._state._listen_state(changed)
        def release():
            self._state._unlisten_state(changed)
        return release
'''
lines=s.splitlines(keepends=True);lines[n.lineno-1:n.end_lineno]=[source+'\n'];s=''.join(lines)
# Internal storage and transactions are not public string APIs. Consumer ports
# hold FieldProxy values; no compatibility aliases or old entry points remain.
s=s.replace('self.parameters','self._parameters')
idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
renames={'get_resolved_value':'_read_field','get_saved_resolved_value':'_read_saved_field','update_parameter':'_write_field','on_state_changed':'_listen_state','off_state_changed':'_unlisten_state','on_resolved_changed':'_listen_resolved','off_resolved_changed':'_unlisten_resolved'}
for _,node in idx.indexed_nodes_of_type(ast.FunctionDef):
 if node.name in {'reset_parameter','signature_default'}:
  edits.append((node.lineno-1,node.end_lineno,''));continue
 if node.name=='fields':
  edits.append((node.lineno-1,node.end_lineno,'    def fields(self) -> RootFields:\n        return RootFields(self)\n\n    def _field_at(self, path: str) -> FieldProxy:\n        return FieldProxy(self, path)\n\n    def field(self, owner: ParameterOwner, name: str) -> FieldProxy:\n        matches = [path for path, declaration in self._parameter_structure.declarations.items() if declaration.name == name and self._parameter_structure.owner_paths[path] is owner]\n        if len(matches) != 1:\n            raise FieldAccessError(f"Expected one declared {owner!r}.{name}, found {len(matches)}; use the declaration namespace for repeated owners")\n        return self._field_at(matches[0])\n'));continue
 if node.name in renames:
  old=''.join(lines[node.lineno-1:node.end_lineno]);new=old.replace('def '+node.name+'(', 'def '+renames[node.name]+'(',1)
  if node.name in {'get_resolved_value','get_saved_resolved_value','update_parameter'}:
   new=new.replace('param_name: str','field: FieldProxy',1)
   # The existing transaction remains the state owner's work. Resolve its
   # canonical declaration key once, not at each consumer.
   parsed=ast.parse(textwrap.dedent(new)).body[0];first=parsed.body[0]
   insert_after=first.end_lineno if isinstance(first,ast.Expr)and isinstance(first.value,ast.Constant)and isinstance(first.value.value,str)else 1
   parts=new.splitlines(keepends=True);parts.insert(insert_after,'        param_name = field._path\n');new=''.join(parts)
  edits.append((node.lineno-1,node.end_lineno,new))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines)
# Migrate ObjectState's own calls while removing the public entry points.
idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
for _,node in idx.indexed_nodes_of_type(ast.Call):
 if not isinstance(node.func,ast.Attribute):continue
 name=node.func.attr
 if name=='reset_parameter':
  replacement=ast.Call(func=ast.Attribute(value=ast.Call(func=ast.Attribute(value=node.func.value,attr='_field_at',ctx=ast.Load()),args=[node.args[0]],keywords=[]),attr='reset',ctx=ast.Load()),args=[],keywords=[])
 elif name in renames:
  args=list(node.args)
  if name in {'get_resolved_value','get_saved_resolved_value','update_parameter'}:
   args[0]=ast.Call(func=ast.Attribute(value=node.func.value,attr='_field_at',ctx=ast.Load()),args=[args[0]],keywords=[])
  replacement=ast.Call(func=ast.Attribute(value=node.func.value,attr=renames[name],ctx=ast.Load()),args=args,keywords=node.keywords)
 else:continue
 before=lines[node.lineno-1][:node.col_offset];after=lines[node.end_lineno-1][node.end_col_offset:];edits.append((node.lineno-1,node.end_lineno,before+ast.unparse(ast.fix_missing_locations(replacement))+after))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines);compile(s,str(P),'exec');P.write_text(s)
