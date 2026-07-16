from __future__ import annotations

import io
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ragdoll.cli import app
from ragdoll.config import Settings
from ragdoll.domain import (
    ClarificationOption,
    ClarificationQuestion,
    DocumentStatus,
    DossierStatus,
    EvidenceChunk,
    EvidenceDocument,
    EvidenceLevel,
    GroundedAnswer,
    GroundedClaim,
    InvestigationStatus,
    RelevanceBatch,
    RelevanceJudgment,
    ResearchDossier,
)
from ragdoll.interactive import InteractiveResearch
from ragdoll.mascot import Mascot
from ragdoll.planning import InterviewTurn
from ragdoll.providers import FakeProvider, ProviderError
from ragdoll.storage import Workspace


class ScriptedSession:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.messages: list[str] = []

    def prompt(self, message: str) -> str:
        self.messages.append(message)
        return next(self.responses)


class StaticSource:
    name = "static"

    def __init__(self, papers) -> None:
        self.papers = papers

    def search(self, query: str, limit: int = 25):
        return [
            paper.model_copy(update={"queries": {query}, "source_ranks": [index]})
            for index, paper in enumerate(self.papers[:limit], 1)
        ]


class NoopCrossref:
    def enrich(self, paper):
        return paper


def clarification() -> ClarificationQuestion:
    return ClarificationQuestion(
        id="goal",
        question="What should this investigation accomplish?",
        options=(
            ClarificationOption(label="Understand", description="Build foundations"),
            ClarificationOption(label="Compare", description="Compare methods"),
            ClarificationOption(label="Explore", description="Find directions"),
        ),
    )


def relevance(papers) -> RelevanceBatch:
    return RelevanceBatch(
        judgments=[
            RelevanceJudgment(
                paper_id=paper.id,
                topical_relevance=4,
                criteria_fit=4,
                axis_coverage=["architecture", "reproducibility"],
                evidence_availability=2,
                confidence=1,
                rationale="Matches the approved investigation.",
            )
            for paper in papers
        ]
    )


def make_research(tmp_path, provider, responses, papers) -> InteractiveResearch:
    console = Console(file=io.StringIO(), force_terminal=False, width=100)
    research = InteractiveResearch(
        tmp_path,
        Settings(animate=False),
        provider,
        console,
        cast(Any, ScriptedSession(responses)),
    )
    research.service.openalex = cast(Any, StaticSource(papers))
    research.service.arxiv = cast(Any, StaticSource([]))
    research.service.crossref = cast(Any, NoopCrossref())
    return research


def test_complete_interactive_flow(tmp_path, brief, plan, papers) -> None:
    provider = FakeProvider(
        [
            InterviewTurn(complete=False, question=clarification()),
            InterviewTurn(complete=True),
            brief,
            plan,
            relevance(papers),
        ]
    )
    research = make_research(
        tmp_path,
        provider,
        [
            "1",
            "a",
            "/inspect 1",
            "/unstage 1",
            "/stage 1",
            "/staged",
            "/candidates",
            "/plan",
            "/brief",
            "/export",
            "/help",
            "/unknown",
            "/quit",
        ],
        papers,
    )
    result = research.start("video generation")
    assert result.status == InvestigationStatus.REVIEW
    assert len(result.answers) == 1
    assert (tmp_path / ".ragdoll" / "exports" / result.id / "reading-list.md").exists()
    output = cast(io.StringIO, research.console.file).getvalue()
    assert "Enter my own answer" in output
    assert "Paper candidates" in output
    assert "Unknown command" in output


def test_custom_answer_validation_and_plan_edit(tmp_path, brief, plan, papers) -> None:
    revised = plan.model_copy(update={"title": "Revised plan"})
    provider = FakeProvider(
        [
            InterviewTurn(complete=False, question=clarification()),
            InterviewTurn(complete=True),
            brief,
            plan,
            revised,
        ]
    )
    research = make_research(
        tmp_path,
        provider,
        ["x", "4", "", "2", "e", "prefer recent work", "q"],
        papers,
    )
    result = research.start("video")
    assert result.plan == revised
    assert result.status == InvestigationStatus.PLAN_REVIEW


def test_resume_and_helpers(tmp_path, investigation, brief, plan, papers, monkeypatch) -> None:
    research = make_research(tmp_path, FakeProvider([]), ["/quit"], papers)
    assert research.resume(investigation) == investigation
    assert research._resolve_id(investigation, "1") == investigation.papers[0].paper.id
    with pytest.raises(KeyError):
        research._resolve_id(investigation, "999")
    research._inspect(investigation, "missing")

    monkeypatch.setattr(research, "_interview", lambda value: value)
    interviewing = investigation.model_copy(update={"status": InvestigationStatus.INTERVIEW})
    assert research.resume(interviewing) == interviewing
    monkeypatch.setattr(research, "_review_plan", lambda value: value)
    reviewing = investigation.model_copy(update={"status": InvestigationStatus.PLAN_REVIEW})
    assert research.resume(reviewing) == reviewing

    searching = investigation.model_copy(update={"status": InvestigationStatus.SEARCHING})
    monkeypatch.setattr(research.service, "execute", lambda value: (investigation, []))
    monkeypatch.setattr(research, "_review_collection", lambda value: value)
    assert research.resume(searching) == investigation


def test_dossier_requires_explicit_download_approval(tmp_path, investigation, papers) -> None:
    research = make_research(tmp_path, FakeProvider([]), ["n"], papers)
    research.service.workspace.save(investigation)
    updated = research._dossier(investigation)
    assert updated.dossier_status == DossierStatus.AWAITING_APPROVAL
    assert research.service.workspace.list_documents(investigation.id) == []


def test_collection_evidence_dossier_and_purge_commands(
    tmp_path, investigation, papers, monkeypatch: pytest.MonkeyPatch
) -> None:
    research = make_research(
        tmp_path,
        FakeProvider([]),
        [
            "",
            "/stage 99",
            "/ask What improves coherence?",
            "/evidence chunk-1",
            "/evidence missing",
            "/sources",
            "/dossier",
            "/dossier refresh Missing",
            "/purge-evidence",
            "n",
            "/purge-evidence",
            "yes",
            "/quit",
        ],
        papers,
    )
    workspace = research.service.workspace
    workspace.save(investigation)
    document = EvidenceDocument(
        id="doc-1",
        investigation_id=investigation.id,
        paper_id=investigation.papers[0].paper.id,
        source="fixture",
        evidence_level=EvidenceLevel.ABSTRACT,
        status=DocumentStatus.FALLBACK,
    )
    chunk = EvidenceChunk(
        id="chunk-1",
        investigation_id=investigation.id,
        paper_id=document.paper_id,
        document_id=document.id,
        locator="abstract",
        evidence_level=EvidenceLevel.ABSTRACT,
        text="Video diffusion improves coherence.",
        sha256="a" * 64,
    )
    workspace.save_document(document, [chunk])
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="1 abstract",
        sections=[
            {
                "title": "Executive summary",
                "claims": [{"text": "Coherence improves.", "chunk_ids": [chunk.id]}],
            }
        ],
    )
    workspace.save_dossier(investigation.id, dossier)
    answer = GroundedAnswer(
        question="What improves coherence?",
        claims=[GroundedClaim(text="Diffusion improves coherence.", chunk_ids=[chunk.id])],
        explanation="Cited evidence.",
    )
    monkeypatch.setattr(research.service, "ask", lambda value, question: answer)

    def purge_failure(value):
        raise OSError("permission denied")

    monkeypatch.setattr(research.service, "purge_evidence", purge_failure)

    result = research._review_collection(investigation)

    assert result == investigation
    output = cast(io.StringIO, research.console.file).getvalue()
    assert "Diffusion improves coherence" in output
    assert "Evidence citation not found" in output
    assert "Dossier section not found" in output
    assert "Evidence purge failed" in output


def test_dossier_approval_refresh_resume_and_build_paths(
    tmp_path, investigation, papers, monkeypatch: pytest.MonkeyPatch
) -> None:
    research = make_research(tmp_path, FakeProvider([]), ["y"], papers)
    research.service.workspace.save(investigation)
    monkeypatch.setattr(research, "_build_dossier", lambda value: value)
    approved = research._dossier(investigation)
    assert approved.dossier_status == DossierStatus.AWAITING_APPROVAL
    assert "send selected passages to openai" in cast(Any, research.session).messages[-1]

    unstaged = investigation.model_copy(
        update={
            "papers": [item.model_copy(update={"staged": False}) for item in investigation.papers]
        }
    )
    assert research._dossier(unstaged) == unstaged

    chunk = EvidenceChunk(
        id="chunk-1",
        investigation_id=investigation.id,
        paper_id=investigation.papers[0].paper.id,
        document_id="doc-1",
        locator="abstract",
        evidence_level=EvidenceLevel.ABSTRACT,
        text="Evidence.",
        sha256="a" * 64,
    )
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="1 abstract",
        sections=[
            {
                "title": "Executive summary",
                "claims": [{"text": "Evidence.", "chunk_ids": [chunk.id]}],
            },
            {"title": "Open questions", "claims": []},
        ],
    )
    research.service.workspace.save_dossier(investigation.id, dossier)
    assert research._dossier(investigation, "refresh Open questions") == investigation
    assert research._dossier(investigation, "refresh Open questions") == investigation

    partial = investigation.model_copy(update={"dossier_status": DossierStatus.PARTIAL})
    research.session = cast(Any, ScriptedSession(["y"]))
    assert research._dossier(partial) == partial


def test_build_dossier_success_and_failure(
    tmp_path, investigation, papers, monkeypatch: pytest.MonkeyPatch
) -> None:
    research = make_research(tmp_path, FakeProvider([]), [], papers)
    research.service.workspace.save(investigation)
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="No usable evidence was indexed.",
        sections=[{"title": "Executive summary", "claims": []}],
    )
    updated = investigation.model_copy(update={"dossier_status": DossierStatus.PARTIAL})
    monkeypatch.setattr(
        research.service,
        "build_dossier",
        lambda value: (updated, dossier, ["abstract fallback"]),
    )
    assert research._build_dossier(investigation) == updated

    def fail(value):
        raise ProviderError("bad citations")

    monkeypatch.setattr(research.service, "build_dossier", fail)
    assert research._build_dossier(investigation) == investigation


def test_mascot_static_and_animated(monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=False)
    mascot = Mascot(console, enabled=False)
    mascot.welcome()
    with mascot.activity("planning", "Thinking"):
        pass
    mascot.result("Done")
    mascot.result("Failed", success=False)
    rendered = output.getvalue()
    assert "RAGdoll" in rendered
    assert "(x)-(x)" in rendered
    assert "Thinking" in rendered

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    animated = Mascot(console, enabled=True)
    with animated.activity("searching", "Searching"):
        time.sleep(0.25)


def test_cli_read_only_and_workspace_commands(
    tmp_path: Path, investigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["--version"]).exit_code == 0
    assert runner.invoke(app, ["init"]).exit_code == 0
    Workspace(tmp_path).save(investigation)
    assert investigation.id in runner.invoke(app, ["investigations"]).stdout
    assert investigation.original_prompt in runner.invoke(app, ["show", investigation.id]).stdout
    result = runner.invoke(app, ["export", investigation.id, "--format", "json"])
    assert result.exit_code == 0
    assert (tmp_path / ".ragdoll" / "exports" / f"{investigation.id}.json").exists()
    workspace = Workspace(tmp_path)
    document = EvidenceDocument(
        id="doc-cli",
        investigation_id=investigation.id,
        paper_id=investigation.papers[0].paper.id,
        source="fixture",
        evidence_level=EvidenceLevel.ABSTRACT,
        status=DocumentStatus.FALLBACK,
    )
    chunk = EvidenceChunk(
        id="chunk-cli",
        investigation_id=investigation.id,
        paper_id=document.paper_id,
        document_id=document.id,
        locator="abstract",
        evidence_level=EvidenceLevel.ABSTRACT,
        text="Evidence.",
        sha256="a" * 64,
    )
    workspace.save_document(document, [chunk])
    workspace.save_dossier(
        investigation.id,
        ResearchDossier(
            title="Dossier",
            evidence_summary="1 abstract",
            sections=[
                {
                    "title": "Summary",
                    "claims": [{"text": "Evidence.", "chunk_ids": [chunk.id]}],
                }
            ],
        ),
    )
    assert runner.invoke(app, ["export", investigation.id, "--format", "dossier"]).exit_code == 0
    assert (
        runner.invoke(app, ["export", investigation.id, "--format", "dossier-json"]).exit_code == 0
    )
    assert runner.invoke(app, ["doctor"]).exit_code == 0
    monkeypatch.setenv("RAGDOLL_PROVIDER", "ollama")

    class TagsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"models": [{"name": "qwen3:4b"}]}

    monkeypatch.setattr("ragdoll.cli.httpx.get", lambda *args, **kwargs: TagsResponse())
    assert "Ollama" in runner.invoke(app, ["doctor"]).stdout
    assert runner.invoke(app, ["export", investigation.id, "--format", "pdf"]).exit_code != 0


def test_cli_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()
    assert runner.invoke(app, ["--topic", "topic"]).exit_code == 2
    assert runner.invoke(app, ["resume"]).exit_code == 2
    assert runner.invoke(app, ["show", "missing"]).exit_code == 2
