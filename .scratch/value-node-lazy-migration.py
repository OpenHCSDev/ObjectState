"""Move declaration/data operations into their admitted family in one source batch."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index
p = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/lazy_factory.py')
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
'_resolved_dataclass_annotations': '',
'_normalized_config_type': '',
'_declared_config_field_names': '',
'resolve_lazy_configurations_for_serialization': '''def resolve_lazy_configurations_for_serialization(data: Any) -> Any:
    """Admit one input graph; members own recursive resolution and reconstruction.

    Inheritance requests require an active configuration context. Constructor
    failures propagate; serialization never bypasses a domain constructor.
    """
    return FieldValue.of(data).for_serialization()
''',
'create_dataclass_for_editing': '''def create_dataclass_for_editing(dataclass_type: Type[T], source_config: Any, preserve_values: bool = False, context_provider: Optional[Callable[[Any], None]] = None) -> T:
    """Preserve stored meanings, or create inherited drafts without inventing nulls."""
    declaration = FieldValue.of(dataclass_type)
    constructor = declaration.require_config_type()
    if context_provider:
        context_provider(source_config)
    source = FieldValue.of(source_config)
    annotations = declaration.annotations_for(constructor)
    values = {
        field.name: (source.read_raw(field.name) if preserve_values
                     else FieldValue.of(annotations.get(field.name, field.type)).editing_default())
        for field in declaration.declared_fields() if field.init
    }
    return constructor(**{name: member.stored for name, member in values.items()})
''',
}
edits = [(*span(n), replacements[n.name]) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in replacements]
owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LazyDataclassFactory')
method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == '_introspect_dataclass_fields')
edits.append((*span(method), '''    @staticmethod
    def _introspect_dataclass_fields(base, debug_template):
        """Declaration members produce their field definition, not type flags."""
        annotations = base.annotations_for(base.stored)
        definitions = []
        for declaration in base.declared_fields():
            annotation = annotations.get(declaration.name, declaration.type)
            final_type, field_definition = FieldValue.of(resolve_annotated(annotation)).lazy_field(declaration, annotation)
            definitions.append((declaration.name, final_type, field_definition))
            logger.debug(debug_template.format(
                field_name=declaration.name,
                original_type=declaration.type,
                has_default=(declaration.default is not MISSING or declaration.default_factory is not MISSING),
                final_type=final_type,
            ))
        return definitions
'''))
for a,b,text in sorted(edits, reverse=True):s=s[:a]+text+s[b:]
s=s.replace('_resolved_dataclass_annotations(', 'DataclassFieldAccess.annotations_for(')
compile(s,str(p),'exec')
p.write_text(s)

# The old context-specific declaration cache is replaced by the shared capability.
p = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/context_manager.py')
s=p.read_text()
tree=SourceModule.from_source_path(p,s).parse().module
lines=s.splitlines(keepends=True);starts=[0]
for line in lines:starts.append(starts[-1]+len(line))
n=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_declared_config_fields')
a,b=span(n);s=s[:a]+s[b:]
compile(s,str(p),'exec');p.write_text(s)
