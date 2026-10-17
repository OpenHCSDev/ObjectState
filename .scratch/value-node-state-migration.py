"""One-shot authored owner migration; NRA supplies original syntax positions."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index

path = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py')
source = path.read_text()
tree = SourceModule.from_source_path(path, source).parse().module
syntax = module_syntax_index(tree)
lines = source.splitlines(keepends=True)
starts = [0]
for line in lines:
    starts.append(starts[-1] + len(line))
def pos(line, column):
    return starts[line - 1] + len(lines[line - 1].encode()[:column].decode())
def method_span(method):
    first = min([method.lineno] + [d.lineno for d in method.decorator_list])
    return starts[first - 1], starts[method.end_lineno]
owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ObjectState')
methods = {n.name: n for n in owner.body if isinstance(n, ast.FunctionDef)}
replacements = {
'_seed_callable_identity_memo': '',
'_extract_all_parameters_flat': '',
'_dataclass_parameter_updates': '',
'_compute_dirty_fields': '''    def _compute_dirty_fields(self) -> set[str]:
        """Compare admitted effective members, without a second domain normalizer."""
        if self._live_resolved is None:
            return set()
        return {
            path for path in self._live_resolved.keys() | self._saved_resolved.keys()
            if self._live_resolved.get(path, Unset()) != self._saved_resolved.get(path, Unset())
        }
''',
'_replace_parameter_structure': '''    def _replace_parameter_structure(
        self, obj, *, exclude_params=None, initial_values=None,
    ) -> None:
        """Admit one value graph and replace its declaration topology atomically."""
        self._target = FieldValue.of(obj)
        self._parameters.clear()
        self._parameter_structure = ParameterStructure.for_target(self._target, exclude_params)
        self._target.extract_parameters(
            type(self), self._parameters, self._parameter_structure,
            exclusions=exclude_params or (),
        )
        for path, datum in (initial_values or {}).items():
            member = FieldValue.of(datum)
            self._parameters[path] = member
            self._parameters.update(member.descendant_values(path, self._parameters))
        self._index_parameter_paths()
''',
'_resolve_parameter_snapshot': '''    @classmethod
    def _resolve_parameter_snapshot(
        cls, parameters, values, structure, current_node, scope_id,
        ancestor_objects_with_scopes, *, use_saved, field_paths=None,
    ):
        """Resolve admitted members; terminal parents suppress retained child drafts."""
        from objectstate.context_manager import build_context_stack
        from objectstate.dual_axis_resolver import resolve_with_provenance

        snapshot = {}
        provenance = {}
        with build_context_stack(
            object_instance=current_node.stored,
            ancestor_objects_with_scopes=ancestor_objects_with_scopes,
            current_scope_id=scope_id, use_live=not use_saved,
        ):
            def resolve(path):
                if path in snapshot:
                    return snapshot[path]
                address = DottedFieldPath(path)
                owner = structure.owner_paths[path]
                if address.parent.value:
                    raw, owner = resolve(address.parent.value).resolved_child(address.field_name, owner)
                else:
                    raw = structure.reconstruct_member(path, values, current_node)
                def inherited():
                    if not isinstance(owner, type):
                        return Unset()
                    result = resolve_with_provenance(owner, address.field_name)
                    provenance[path] = (result.source_scope, result.source_type)
                    return FieldValue.of(result.value)
                snapshot[path] = raw.resolve(inherited)
                return snapshot[path]
            for path in parameters:
                if field_paths is None or path in field_paths:
                    resolve(path)
        return snapshot, provenance
''',
'notification_fields_for_value_changes': '''    def notification_fields_for_value_changes(self, changed_values) -> set[str]:
        """The member owns whether its registered descendants carry the change."""
        fields = set()
        for path, (before, after) in changed_values.items():
            member = self._parameters.get(path, Unset())
            fields.update(member.notification_paths(path, self._parameter_structure))
            fields.update(changed_structural_leaf_paths(
                owner_field_path=DottedFieldPath(path), old_value=before, new_value=after,
            ))
        return fields
''',
'_get_param_value_from_target': '''    def _get_param_value_from_target(self, target, param_name):
        """A missing descendant under a terminal parent is absent, never null."""
        current = target
        for part in DottedFieldPath(param_name).parts:
            try:
                current = current.read_raw(part)
            except AttributeError:
                return Unset()
        return current
''',
 'to_object': '''    def to_object(self, *, update_delegate=False, sync_delegate=True):
        """Materialize through the admitted root; apply a cached result only on request."""
        if sync_delegate:
            self._check_and_sync_delegate()
        if self._cached_object is None:
            values = self._parameter_structure.direct_values('', self._parameters, self._target)
            self._cached_object = self._target.with_fields(values)
            self._cached_object_applied = False
        node = self._cached_object
        if update_delegate and not self._cached_object_applied:
            if self._delegate_attr is None:
                self.object_instance = node.stored
            else:
                setattr(self.object_instance, self._delegate_attr, node.stored)
            self._target = node
            self._cached_object_applied = True
        return node.stored
''',
}
edits = [(*method_span(methods[name]), replacement) for name, replacement in replacements.items()]
for start, end, replacement in sorted(edits, reverse=True):
    source = source[:start] + replacement + source[end:]
# The selected methods above no longer carry the source's old datatype switch.
source = source.replace('_extraction_target', '_target')
compile(source, str(path), 'exec')
path.write_text(source)
