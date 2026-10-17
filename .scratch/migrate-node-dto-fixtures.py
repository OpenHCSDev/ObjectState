"""One-shot migration of the source-adjudicated DTO fixture constructors."""
import ast
import json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule, module_syntax_index

root = Path('/home/ts/wt/openhcs-declared-fields/tests/unit/agent')
records = []
for filename in ('test_mcp_server.py', 'test_mcp_dev_client_knowledge_renderers.py', 'test_object_state_field_help_service.py', 'test_ui_bridge_service.py'):
    path = root / filename
    source = path.read_text()
    tree = SourceModule.from_source_path(path, source).parse().module
    syntax = module_syntax_index(tree)
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    def pos(line, col):
        return starts[line - 1] + len(lines[line - 1].encode()[:col].decode())
    def span(node):
        return pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset)
    edits = []
    needs_declaration = False
    for _, node in syntax.indexed_nodes_of_type(ast.Call):
        if not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name not in {'UiObjectStateFieldSummary', 'UiObjectStateFieldProjection', 'UiObjectStateScopeSummary', 'UiObjectStateFieldScopeProjection', 'UiObjectStateFieldProvenance', 'UiObjectStateFieldHelpResult', 'UiObjectStateValuePreview'}:
            continue
        for keyword in node.keywords:
            if keyword.arg == 'object_state_path_type':
                old = ast.unparse(keyword.value)
                if isinstance(keyword.value, ast.Constant):
                    module, _, qualname = keyword.value.value.rpartition('.')
                    replacement = f'declared_by=UiObjectStateFieldDeclaration(module={module!r}, qualname={qualname!r})'
                else:
                    replacement = f'declared_by=UiObjectStateFieldDeclaration(module={old}.rpartition(".")[0], qualname={old}.rpartition(".")[2])'
                edits.append((*span(keyword), replacement))
                needs_declaration = True
            elif keyword.arg in {'object_type', 'raw_value_type', 'resolved_value_type', 'source_type', 'help_target_type', 'type_name', 'is_none'}:
                if keyword.lineno != keyword.end_lineno:
                    raise RuntimeError(f'Unadjudicated multi-line keyword {path}:{keyword.lineno}')
                edits.append((starts[keyword.lineno - 1], starts[keyword.lineno], ''))
        if name == 'UiObjectStateValuePreview':
            edits.append((*span(node.func), 'UiObjectStateTextPreview'))
            if node.args:
                if len(node.args) != 3:
                    raise RuntimeError('Expected old three-field positional preview')
                edits.append((span(node.args[0])[0], span(node.args[2])[0], ''))
        if name == 'UiObjectStateFieldProvenance' and node.args:
            if len(node.args) != 3:
                raise RuntimeError('Expected old three-field positional provenance')
            edits.append((span(node.args[1])[0], span(node.args[2])[0], ''))
        records.append((filename, node.lineno, name))
    for _, node in syntax.indexed_nodes_of_type(ast.ImportFrom):
        for item in node.names:
            if item.name == 'UiObjectStateValuePreview':
                edits.append((*span(item), 'UiObjectStateTextPreview'))
    if needs_declaration:
        after = max((node.end_lineno for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == '__future__'), default=0)
        edits.append((starts[after], starts[after], 'from formbridge.bridge.dto import UiObjectStateFieldDeclaration\n'))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    compile(source, str(path), 'exec')
    path.write_text(source)
print(json.dumps(records, indent=2))
