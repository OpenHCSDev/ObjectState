"""One-shot migration of reviewed normalization expressions; source evidence retained."""
import ast
import json
from itertools import accumulate
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule
from nominal_refactor_advisor.source_geometry import SourceByteSpan

root = Path('/home/ts/wt/objectstate-declared-fields/src/objectstate')
records = []
for path in root.glob('*.py'):
    source = path.read_text()
    parsed = SourceModule.from_source_path(path, source).parse()
    lines = tuple(source.splitlines(keepends=True))
    offsets = tuple(accumulate((len(line) for line in lines), initial=0))
    edits = []
    for node in ast.walk(parsed.module):
        replacement = None
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
            call, fallback = node.values
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == 'get_base_type_for_lazy' and len(call.args) == 1
                    and ast.dump(call.args[0]) == ast.dump(fallback)):
                replacement = f'resolve_declared_type({ast.get_source_segment(source, call.args[0])})'
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == '_normalize_type':
            replacement = f'resolve_declared_type({ast.get_source_segment(source, node.args[0])})'
        elif isinstance(node, ast.FunctionDef) and node.name == '_normalize_type' and path.name == 'context_manager.py':
            start = min((d.lineno for d in node.decorator_list), default=node.lineno)
            edits.append((offsets[start - 1], offsets[node.end_lineno], ''))
            continue
        elif isinstance(node, ast.ImportFrom) and node.module == 'objectstate.lazy_factory' and len(node.names) == 1 and node.names[0].name == 'get_base_type_for_lazy':
            edits.append((offsets[node.lineno - 1], offsets[node.end_lineno], ''))
            continue
        if replacement is not None:
            begin, end = SourceByteSpan.require_node(node).character_offsets(lines, offsets)
            edits.append((begin, end, replacement))
    # Parent replacement wins over obsolete nodes inside the removed wrapper.
    edits = [edit for edit in edits if not any(other[0] <= edit[0] and edit[1] <= other[1] and other != edit for other in edits)]
    if not edits:
        continue
    changed = source
    for begin, end, replacement in sorted(edits, reverse=True):
        changed = changed[:begin] + replacement + changed[end:]
    if 'from python_introspect import resolve_declared_type\n' not in changed:
        # All selected modules already have ordinary imports; put the public owner beside them.
        tree = ast.parse(changed)
        imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        last = imports[-1]
        changed_lines = changed.splitlines(keepends=True)
        changed_lines.insert(last.end_lineno, 'from python_introspect import resolve_declared_type\n')
        changed = ''.join(changed_lines)
    compile(changed, str(path), 'exec')
    path.write_text(changed)
    records.append({'path': str(path), 'edits': len(edits)})
Path('/home/ts/.cache/agent-scratch/objectstate-declared-fields/normalization-migration.json').write_text(json.dumps(records, indent=2))
print(json.dumps(records, indent=2))
