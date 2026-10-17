"""Repair declaration lifetime and remove the mixed owner/payload type index."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py');s=P.read_text()
s=s.replace('self._structure = state._parameter_structure','self._owner = state._parameter_structure.binding_owner(path)')
s=s.replace('return self._structure.owner_paths[self._path]','return self._owner')
s=s.replace('return self._structure is self._state._parameter_structure and self._path in self._state._parameters','return self._path in self._state._parameter_structure.declarations and self._state._parameter_structure.binding_owner(self._path) is self._owner')
s=s.replace('self._structure is other._structure','self._owner is other._owner').replace('id(self._structure)','id(self._owner)')
s=s.replace('return self._structure.declarations[self._path]','self._require_present()\n        return self._structure.declarations[self._path]')
s=s.replace('return self._state._parameters[self._path]', 'return self._state._parameters.get(self._path, Unset())')
s=s.replace('return self._state._read_saved_field(self)','self._require_present()\n        return self._state._read_saved_field(self)')
s=s.replace('''    def dirty(self):
        self._state._ensure_live_resolved()''','''    def dirty(self):
        self._require_present()
        self._state._ensure_live_resolved()''')
# All actual owners are admitted at one declaration boundary. No overwrite with
# the contained value's nominal class is permitted.
s=s.replace('structure.declare(dotted_path, info)','structure.declare(dotted_path, info, owner_target)')
s=s.replace('                structure.owner_paths[dotted_path] = nested_type\n','').replace('                structure.owner_paths[dotted_path] = owner_target\n','')
a=s.index('            # Check if this is a nested dataclass\n');b=s.index('                # Store the nested dataclass instance in parameters',a)
s=s[:a]+'''            if is_dataclass(type(current_value)):
'''+s[b:]
s=s.replace('local_invalidations = set(changed_semantic_params)','local_invalidations = set(changed_storage_params)')
# Read-time reconstruction consumes the projection's own shape. Declaration
# ownership is never also a payload-type tag.
s=s.replace('''            prefix_type = self._path_to_type.get(prefix)
            if not (isinstance(prefix_type, type) and is_dataclass(prefix_type)):
                continue

''','')
s=s.replace('for path, typ in self._path_to_type.items():','for path, typ in self._parameter_structure.container_types(self._parameters):')
s=s.replace('self._path_to_type','self._parameter_structure.owner_paths')
s=s.replace('''self._parameter_structure.owner_paths[path] is owner''','''self._parameter_structure.binding_owner(path) is owner''')
idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
def span(n):return min([n.lineno]+[d.lineno for d in n.decorator_list])-1,n.end_lineno
for _,c in idx.indexed_nodes_of_type(ast.ClassDef):
 for n in c.body:
  if not isinstance(n,ast.FunctionDef):continue
  text=None
  if c.name=='FieldProxy'and n.name=='state':
   # Insert the shared live-schema projection before the existing property.
   a,b=span(n);edits.append((a,a,'''    @property
    def _structure(self):
        return self._state._parameter_structure

'''))
  if c.name=='RootFields'and n.name=='_structure':text=''
  if c.name=='RootFields'and n.name=='present':
   a,b=span(n);edits.append((b,b,'''
    __hash__ = None

    def __eq__(self, other):
        return isinstance(other, RootFields) and self._state is other._state
'''))
  if c.name=='ObjectState'and n.name in {'_path_to_type','_get_nested_dataclass_type','type_for_path'}:text=''
  if c.name=='ObjectState'and n.name=='_read_field':text='''    def _read_field(self, field: FieldProxy) -> Any:
        """Read this projection, preserving scalar terminals and nominal shape."""
        self._check_and_sync_delegate()
        self._ensure_live_resolved()
        return self._parameter_structure.reconstruct(field._path, self._live_resolved, self._extraction_target, resolved=True)
'''
  if c.name=='ObjectState'and n.name=='_read_saved_field':text='''    def _read_saved_field(self, field: FieldProxy) -> Any:
        """The saved projection owns its own payload, independently of live data."""
        self._check_and_sync_delegate()
        self._ensure_saved_resolved()
        return self._parameter_structure.reconstruct(field._path, self._saved_resolved, self._extraction_target, resolved=True)
'''
  if c.name=='ObjectState'and n.name=='_recompute_invalid_fields':text='''    def _recompute_invalid_fields(self, sources: ResolutionSources) -> set[str]:
        """Use the same resolver for admitted invalid fields as for a full snapshot."""
        if self._live_resolved is None:
            return set()
        selected = self._invalid_fields & self._parameters.keys()
        snapshot, provenance = self._resolve_parameter_snapshot(
            self._parameters, self._parameters, self._parameter_structure,
            self.to_object(update_delegate=False, sync_delegate=False),
            self.scope_id, sources.ancestors, use_saved=False, field_paths=selected,
        )
        changed = {
            path: (self._live_resolved.get(path, Unset()), value)
            for path, value in snapshot.items()
            if not semantic_values_equal(self._live_resolved.get(path, Unset()), value)
        }
        self._live_resolved.update(snapshot)
        for path in selected:
            self._live_provenance.pop(path, None)
        self._live_provenance.update(provenance)
        if changed:
            self._set_last_changed_values(changed)
        return self.notification_fields_for_value_changes(changed)
'''
  if c.name=='ObjectState'and n.name=='_resolve_parameter_snapshot':text='''    @classmethod
    def _resolve_parameter_snapshot(
        cls, parameters, values, structure, current_obj, scope_id,
        ancestor_objects_with_scopes, *, use_saved, field_paths=None,
    ):
        """One resolution algorithm for complete and targeted projections.

        A container entry carries the projection's nominal payload; reads rebuild
        its effective children through ParameterStructure.reconstruct. FieldValue
        alone decides whether a stored value invokes inheritance.
        """
        from objectstate.context_manager import build_context_stack
        from objectstate.dual_axis_resolver import resolve_with_provenance

        snapshot = {}
        provenance = {}
        with build_context_stack(
            object_instance=current_obj,
            ancestor_objects_with_scopes=ancestor_objects_with_scopes,
            current_scope_id=scope_id, use_live=not use_saved,
        ):
            for path in parameters if field_paths is None else field_paths:
                raw = values.get(path, Unset())
                def inherited():
                    owner = structure.owner_paths[path]
                    if not isinstance(owner, type):
                        return Unset()  # A callable parameter has no config/MRO layer.
                    result = resolve_with_provenance(owner, structure.declarations[path].name)
                    provenance[path] = (result.source_scope, result.source_type)
                    return result.value
                snapshot[path] = FieldValue.of(raw).resolve(inherited)
        return snapshot, provenance
'''
  if c.name=='ObjectState'and n.name=='reconstruct_top_level_parameters':text='''    def reconstruct_top_level_parameters(self) -> dict[str, Any]:
        """Project local constructor argument names, not the editing address map."""
        self._check_and_sync_delegate()
        return {
            path.field_name: self._parameter_structure.reconstruct(path.value, self._parameters, self._extraction_target)
            for path in self._parameter_structure.direct_paths.get(DottedFieldPath(''), ())
        }
'''
  if c.name=='ObjectState'and n.name=='to_object':
   old=''.join(lines[n.lineno-1:n.end_lineno]);a=old.index('        field_updates = {}');b=old.index('        # Reconstruct the target object',a)
   text=old[:a]+'''        field_updates = self.reconstruct_top_level_parameters()

'''+old[b:]
  if text is not None:
   a,b=span(n);edits.append((a,b,text+'\n'if text else''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines);compile(s,str(P),'exec');P.write_text(s)
P=P.with_name('object_state_registry.py');s=P.read_text().replace('state._path_to_type','state._parameter_structure.owner_paths');P.write_text(s)
