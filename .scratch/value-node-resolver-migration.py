"""Adjudicated resolver migration using NRA source positions, not a new scanner."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index
p = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/dual_axis_resolver.py')
s = p.read_text()
tree = SourceModule.from_source_path(p, s).parse().module
syntax = module_syntax_index(tree)
lines = s.splitlines(keepends=True)
starts = [0]
for line in lines: starts.append(starts[-1] + len(line))
replacements = {
'_direct_owner_field_default': '',
'declared_default': '''def declared_default(container_type: type, field_name: str) -> tuple[Any, type | None]:
    """Defaults come from declarations, never slot descriptors or guessed attributes."""
    base = FieldValue.of(_normalize_to_base(container_type))
    own = base.own_default(field_name)
    own_type = base.stored if own.available() else None
    if own.available():
        return own.stored, own_type
    for declaration in base.configuration_mro():
        value = declaration.own_default(field_name)
        if value.available():
            return value.stored, own_type
    return FieldValue.of(container_type).inherited_default(field_name).stored, own_type
''',
}
edits = []
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name in replacements:
        first = min([n.lineno] + [d.lineno for d in n.decorator_list])
        edits.append((starts[first - 1], starts[n.end_lineno], replacements[n.name]))
for a,b,text in sorted(edits, reverse=True): s=s[:a]+text+s[b:]
compile(s, str(p), 'exec')
p.write_text(s)
