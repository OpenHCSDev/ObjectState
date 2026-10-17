"""Move context operations onto admitted values; remove competing algorithms."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index
p = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/context_manager.py')
s = p.read_text()
tree = SourceModule.from_source_path(p, s).parse().module
syntax = module_syntax_index(tree)
lines = s.splitlines(keepends=True)
starts = [0]
for line in lines: starts.append(starts[-1] + len(line))
def span(n):
    first = min([n.lineno] + [d.lineno for d in n.decorator_list])
    return starts[first - 1], starts[n.end_lineno]
replacements = {
'_merge_nested_dataclass': '',
'_merge_concrete_dataclass': '',
'_record_config_instance': '',
'_extract_from_object_attributes_typed': '',
'_is_compatible_config_type': '',
'extract_all_configs': '''def extract_all_configs(context_obj):
    """Admit an external context and return its typed configuration members."""
    return FieldValue.of(context_obj).context_configs()
''',
'get_context_info': '''def get_context_info() -> Dict[str, Any]:
    current = get_current_temp_global()
    if current is None:
        return {'active': False}
    node = FieldValue.of(current)
    declarations = node.declared_fields()
    return {
        'active': True,
        'type': type(current).__name__,
        'field_count': len(declarations),
        'non_none_fields': sum(node.read_raw(field.name).stored is not None for field in declarations),
    }
''',
'config_context': '''@contextmanager
def config_context(obj, use_live_global: bool = True, scope_id: str | None = None):
    """Enter one admitted layer; field members own merge and raw-read behavior."""
    from objectstate.config import get_base_config_type

    current = get_current_temp_global()
    base = FieldValue.of(current if current is not None else get_base_global_config(use_live=use_live_global))
    incoming = FieldValue.of(obj)
    overrides = {}
    if obj is not None:
        for declaration in FieldValue.of(get_base_config_type()).declared_fields():
            try:
                member = incoming.read_raw(declaration.name)
            except AttributeError:
                continue
            overrides[declaration.name] = member.overlay(base.read_raw(declaration.name))
    merged = base.with_fields(overrides).stored if overrides else base.stored
    types = context_type_stack.get()
    stack = context_layer_stack.get() if current is not None else ContextLayerStack((ContextLayer('', base),))
    if obj is not None:
        stack = stack.with_layer(ContextLayer(scope_id, incoming))
        types += (type(obj),)
    with ExitStack() as resources:
        for variable, value in ((current_temp_global, merged), (context_type_stack, types), (context_layer_stack, stack)):
            resources.callback(variable.reset, variable.set(value))
        yield merged
''',
'_declared_config_fields': '''@functools.cache
def _declared_config_fields(dataclass_type: type) -> tuple[tuple[str, type], ...]:
    """Immutable declaration metadata; the annotation member owns slot admission."""
    annotations = get_type_hints(dataclass_type, include_extras=True)
    return tuple(
        slot
        for field in FieldValue.of(dataclass_type).declared_fields()
        for slot in FieldValue.of(resolve_optional(resolve_annotated(annotations.get(field.name, field.type)))).declared_config_slot(field.name)
    )
''',
}
edits = [(*span(n), replacements[n.name]) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in replacements]
for a, b, replacement in sorted(edits, reverse=True): s = s[:a] + replacement + s[b:]
compile(s, str(p), 'exec')
p.write_text(s)
