"""Artifact readiness does not require a publisher's authentication secret."""

import runpy
from pathlib import Path


CHECKS = runpy.run_path(str(Path(__file__).parents[1] / "scripts/verify_release_ready.py"))


def test_actual_trusted_publishing_workflow_passes_readiness(monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[1])
    assert CHECKS["check_github_workflow"]()


def test_missing_publication_workflow_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not CHECKS["check_github_workflow"]()
