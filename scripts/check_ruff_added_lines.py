#!/usr/bin/env python3
"""Fail when configured Ruff diagnostics touch lines added by a Git diff."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HUNK_HEADER = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@"
)


def _git_output(*arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ("git", *arguments),
        check=True,
        capture_output=True,
        text=not binary,
    )
    return result.stdout


def _changed_python_files(base: str, head: str | None) -> tuple[Path, ...]:
    revision_arguments = (base, head) if head is not None else (base,)
    output = _git_output(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        *revision_arguments,
        "--",
        "*.py",
        binary=True,
    )
    assert isinstance(output, bytes)
    return tuple(
        Path(os.fsdecode(path))
        for path in output.split(b"\0")
        if path
    )


def _added_lines(
    path: Path,
    base: str,
    head: str | None,
) -> frozenset[int]:
    revision_arguments = (base, head) if head is not None else (base,)
    output = _git_output(
        "diff",
        "--unified=0",
        "--no-ext-diff",
        "--no-color",
        *revision_arguments,
        "--",
        os.fspath(path),
    )
    assert isinstance(output, str)
    added: set[int] = set()
    for line in output.splitlines():
        match = HUNK_HEADER.match(line)
        if match is None:
            continue
        first_line = int(match.group(1))
        line_count = int(match.group(2) or "1")
        added.update(range(first_line, first_line + line_count))
    return frozenset(added)


def _ruff_diagnostics(paths: tuple[Path, ...]) -> list[dict[str, object]]:
    result = subprocess.run(
        ("ruff", "check", "--output-format=json", *(os.fspath(path) for path in paths)),
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Ruff did not return JSON diagnostics.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from error
    if result.returncode not in {0, 1}:
        raise RuntimeError(
            f"Ruff failed with exit code {result.returncode}:\n{result.stderr}"
        )
    return diagnostics


def _github_escape(value: object) -> str:
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _relative_diagnostic_path(filename: object) -> Path:
    path = Path(str(filename))
    if path.is_absolute():
        return path.relative_to(Path.cwd())
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Git revision before the change")
    parser.add_argument(
        "--head",
        help="Git revision after the change; omit to inspect the current worktree",
    )
    arguments = parser.parse_args()

    changed_paths = _changed_python_files(arguments.base, arguments.head)
    if not changed_paths:
        print("No changed Python files.")
        return 0

    line_index = {
        path: _added_lines(path, arguments.base, arguments.head)
        for path in changed_paths
    }
    introduced = []
    for diagnostic in _ruff_diagnostics(changed_paths):
        path = _relative_diagnostic_path(diagnostic["filename"])
        location = diagnostic["location"]
        assert isinstance(location, dict)
        row = int(location["row"])
        if row in line_index.get(path, frozenset()):
            introduced.append((path, row, location, diagnostic))

    if not introduced:
        print(
            "Configured Ruff rules report no diagnostics on added Python lines "
            f"across {len(changed_paths)} changed files."
        )
        return 0

    for path, row, location, diagnostic in introduced:
        code = diagnostic["code"]
        message = diagnostic["message"]
        print(
            f"::error file={_github_escape(path)},line={row},"
            f"col={location['column']},title=Ruff {code}::"
            f"{_github_escape(message)}"
        )
    print(f"{len(introduced)} Ruff diagnostics touch added Python lines.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
