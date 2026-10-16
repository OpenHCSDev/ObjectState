"""Deleted classifiers stay deleted; value admission is the only boundary."""

import ast
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "src" / "objectstate"
DELETED_CLASSIFIERS = {"is_container", "is_config_type", "is_dataclass"}


def test_operations_do_not_reclassify_values():
    violations = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        admitted_calls = set()
        if path.name == "declarations.py":
            for declaration in tree.body:
                if isinstance(declaration, ast.FunctionDef) and declaration.name == "_compile_declaration":
                    admitted_calls.update(id(node) for node in ast.walk(declaration))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
            else:
                continue
            if name in DELETED_CLASSIFIERS and id(node) not in admitted_calls:
                violations.append(f"{path.relative_to(SOURCE)}:{node.lineno}: {name}")
    assert not violations, "\n" + "\n".join(sorted(violations))
