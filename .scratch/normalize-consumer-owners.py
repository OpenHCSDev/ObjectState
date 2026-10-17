"""Reviewed consumer migration to the public registered normalization owner."""
import ast
from itertools import accumulate
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule
from nominal_refactor_advisor.source_geometry import SourceByteSpan
roots = [Path('/home/ts/wt/openhcs-declared-fields/openhcs'), Path('/home/ts/wt/pyqt-declared-fields/src')]
for root in roots:
 for path in root.rglob('*.py'):
    source = path.read_text()
    if 'get_base_type_for_lazy' not in source:
        continue
    tree = SourceModule.from_source_path(path, source).parse().module
    lines = tuple(source.splitlines(keepends=True))
    offsets = tuple(accumulate(map(len, lines), initial=0))
    edits = []
    for node in ast.walk(tree):
        replacement = None
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
            call, fallback = node.values
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'get_base_type_for_lazy' and ast.dump(call.args[0]) == ast.dump(fallback):
                replacement = f'resolve_declared_type({ast.get_source_segment(source, call.args[0])})'
        elif isinstance(node, ast.ImportFrom) and node.module in ('objectstate', 'objectstate.lazy_factory'):
            remaining = [alias for alias in node.names if alias.name != 'get_base_type_for_lazy']
            if len(remaining) == len(node.names):
                continue
            replacement = 'from ' + node.module + ' import ' + ', '.join(ast.unparse(alias) for alias in remaining) if remaining else ''
            if not remaining:
                edits.append((offsets[node.lineno-1], offsets[node.end_lineno], ''))
                continue
        if replacement is not None:
            start, end = SourceByteSpan.require_node(node).character_offsets(lines, offsets)
            edits.append((start, end, replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if not any(isinstance(node, ast.ImportFrom) and node.module == 'python_introspect' and any(alias.name == 'resolve_declared_type' for alias in node.names) for node in imports):
        lines = source.splitlines(keepends=True)
        lines.insert(imports[-1].end_lineno, 'from python_introspect import resolve_declared_type\n')
        source = ''.join(lines)
    assert 'get_base_type_for_lazy' not in source, path
    compile(source, str(path), 'exec')
    path.write_text(source)
    print(path)
