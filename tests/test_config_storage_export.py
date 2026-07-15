from __future__ import annotations

from pathlib import Path

import pytest

from ragdoll.config import load_settings
from ragdoll.export import export_investigation
from ragdoll.storage import Workspace


def test_settings_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / ".ragdoll"
    directory.mkdir()
    (directory / "config.toml").write_text(
        "[ragdoll]\nprovider='ollama'\npaper_count=7\n", encoding="utf-8"
    )
    monkeypatch.setenv("RAGDOLL_OLLAMA_MODEL", "local-test")
    settings = load_settings(tmp_path, provider="openai")
    assert settings.provider == "openai"
    assert settings.paper_count == 7
    assert settings.ollama_model == "local-test"


def test_workspace_round_trip_and_schema(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation, "created")
    assert workspace.load(investigation.id) == investigation
    assert workspace.latest() == investigation
    assert workspace.list() == [investigation]
    with pytest.raises(KeyError):
        workspace.load("missing")


def test_empty_workspace(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="no investigations"):
        Workspace(tmp_path).latest()


@pytest.mark.parametrize(
    ("format", "suffix", "needle"),
    [
        ("markdown", "md", "Evidence available to RAGdoll"),
        ("bibtex", "bib", "@article"),
        ("json", "json", '"original_prompt"'),
    ],
)
def test_exports(tmp_path: Path, investigation, format: str, suffix: str, needle: str) -> None:
    path = export_investigation(investigation, tmp_path / f"out.{suffix}", format)
    assert needle in path.read_text(encoding="utf-8")


def test_export_rejects_unknown_format(tmp_path: Path, investigation) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        export_investigation(investigation, tmp_path / "out", "pdf")
