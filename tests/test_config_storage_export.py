from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ragdoll.config import Settings, load_settings
from ragdoll.domain import EvidenceChunk, EvidenceLevel, ResearchDossier
from ragdoll.export import export_dossier, export_investigation, render_dossier
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
    assert workspace.list_investigations() == [investigation]
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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_export_rejects_unknown_format(tmp_path: Path, investigation) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        export_investigation(investigation, tmp_path / "out", "pdf")


def test_workspace_and_exports_reject_symlinks(tmp_path: Path, investigation) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / ".ragdoll").symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError, match="symlink"):
        Workspace(root).initialize()

    guarded = tmp_path / "guarded"
    workspace_directory = guarded / ".ragdoll"
    workspace_directory.mkdir(parents=True)
    (workspace_directory / "ragdoll.db-journal").symlink_to(
        output_target := tmp_path / "journal-victim"
    )
    output_target.write_text("untouched", encoding="utf-8")
    with pytest.raises(OSError, match="unsafe"):
        Workspace(guarded).initialize()
    assert output_target.read_text(encoding="utf-8") == "untouched"

    output_target = tmp_path / "victim.md"
    output_target.write_text("untouched", encoding="utf-8")
    output = tmp_path / "out.md"
    output.symlink_to(output_target)
    with pytest.raises(OSError, match="symlink"):
        export_investigation(investigation, output, "markdown")
    assert output_target.read_text(encoding="utf-8") == "untouched"


def test_dossier_json_empty_sections_and_missing_citations(tmp_path: Path, investigation) -> None:
    chunk = EvidenceChunk(
        id="chunk-1",
        investigation_id=investigation.id,
        paper_id=investigation.papers[0].paper.id,
        document_id="doc-1",
        locator="abstract",
        evidence_level=EvidenceLevel.ABSTRACT,
        text="Evidence text.",
        sha256="a" * 64,
    )
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="1 abstract",
        sections=[
            {"title": "Empty", "claims": []},
            {
                "title": "Summary",
                "claims": [{"text": "A claim.", "chunk_ids": ["missing"]}],
            },
        ],
    )
    rendered = render_dossier(dossier, investigation, {})
    assert "No sufficiently grounded claim" in rendered
    assert "missing: unavailable" in rendered
    output = export_dossier(
        dossier, investigation, {chunk.id: chunk}, tmp_path / "dossier.json", "json"
    )
    assert '"citations"' in output.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported dossier"):
        export_dossier(dossier, investigation, {}, tmp_path / "dossier.txt", "text")


@pytest.mark.parametrize(
    "url",
    [
        "http://ollama.example:11434",
        "ftp://127.0.0.1:11434",
        "https://user:password@ollama.example",
    ],
)
def test_ollama_url_rejects_insecure_remote_transports(url: str) -> None:
    with pytest.raises(ValueError, match="Ollama URL"):
        Settings(ollama_url=url)


def test_ollama_url_normalizes_safe_base_urls() -> None:
    assert Settings(ollama_url="http://localhost:11434/").ollama_url == "http://localhost:11434"
    assert (
        Settings(ollama_url="https://ollama.example/", allow_remote_ollama=True).ollama_url
        == "https://ollama.example"
    )


def test_remote_ollama_requires_opt_in_and_project_cannot_grant_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit"):
        Settings(ollama_url="https://ollama.example")
    directory = tmp_path / ".ragdoll"
    directory.mkdir()
    (directory / "config.toml").write_text(
        "[ragdoll]\nollama_url='https://ollama.example'\nallow_remote_ollama=true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="project config"):
        load_settings(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fulltext_max_pages", 0),
        ("extraction_max_memory_mib", 64),
        ("extraction_max_output_bytes", 300 * 1024 * 1024),
        ("extraction_timeout_seconds", 0),
    ],
)
def test_parser_resource_limits_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        Settings.model_validate({field: value})
