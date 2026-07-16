from __future__ import annotations

import asyncio
import subprocess
import threading
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual.widgets import Input, SelectionList, Static, TextArea
from typer.testing import CliRunner

from ragdoll.cli import app as cli_app
from ragdoll.commands import COMMAND_NAMES, command_help, migration_hint, parse_command
from ragdoll.config import Settings
from ragdoll.domain import (
    ClarificationOption,
    ClarificationQuestion,
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
from ragdoll.editor import ExternalEditorError, edit_text
from ragdoll.interactive import InteractiveResearch
from ragdoll.mascot import (
    FRAME_COUNT,
    SPRITE_FRAMES,
    activity_renderable,
    mascot_renderable,
    pixel_heights,
    pixel_widths,
    sprite_rows,
)
from ragdoll.planning import InterviewTurn
from ragdoll.providers import FakeProvider, ProviderError
from ragdoll.storage import Workspace
from ragdoll.tui import (
    ClarificationScreen,
    ConfirmScreen,
    DetailScreen,
    PapersScreen,
    PlanReviewScreen,
    RagdollApp,
    TimelineCard,
    help_markdown,
    paper_markdown,
    papers_markdown,
    plan_markdown,
)


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


def make_app(tmp_path: Path, provider, papers, **kwargs: Any) -> RagdollApp:
    result = RagdollApp(tmp_path, Settings(animate=False), provider, **kwargs)
    result.service.openalex = cast(Any, StaticSource(papers))
    result.service.arxiv = cast(Any, StaticSource([]))
    result.service.crossref = cast(Any, NoopCrossref())
    return result


async def wait_for(pilot, predicate: Callable[[], bool], attempts: int = 80) -> None:
    for _ in range(attempts):
        await pilot.pause(0.02)
        if predicate():
            return
    raise AssertionError("TUI did not reach the expected state")


@pytest.mark.asyncio
async def test_complete_fullscreen_flow(tmp_path, brief, plan, papers) -> None:
    provider = FakeProvider(
        [
            InterviewTurn(complete=False, question=clarification()),
            InterviewTurn(complete=True),
            brief,
            plan,
            relevance(papers),
        ]
    )
    application = make_app(tmp_path, provider, papers, topic="video generation")

    async with application.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(application.screen, ClarificationScreen))
        await pilot.press("1")
        await wait_for(pilot, lambda: isinstance(application.screen, PlanReviewScreen))
        await pilot.press("a")
        await wait_for(
            pilot,
            lambda: (
                application.investigation is not None
                and application.investigation.status == InvestigationStatus.REVIEW
                and application.query_one("#composer", TextArea).has_focus
            ),
        )
        assert application.investigation is not None
        assert len(application.investigation.answers) == 1
        assert len(application.investigation.papers) == len(papers)
        assert len(application.query(".timeline-card")) >= 5
        assert "staged" in str(application.query_one("#footer", Static).render())


@pytest.mark.asyncio
async def test_custom_answer_plan_edit_back_and_quit(tmp_path, brief, plan, papers) -> None:
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
    application = make_app(tmp_path, provider, papers, topic="video")

    async with application.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(application.screen, ClarificationScreen))
        await pilot.press("4")
        custom = application.screen.query_one("#custom-answer", Input)
        custom.value = "Focus on controllability"
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(application.screen, PlanReviewScreen))
        revision = application.screen.query_one("#plan-revision", Input)
        revision.value = "prefer recent work"
        application.screen.query_one("#edit").press()
        await wait_for(
            pilot,
            lambda: (
                isinstance(application.screen, PlanReviewScreen)
                and application.investigation is not None
                and application.investigation.plan == revised
            ),
        )
        await pilot.press("q")
        await pilot.pause()
    assert application.return_value is not None
    assert application.return_value.plan == revised


@pytest.mark.asyncio
async def test_resume_collection_commands_and_migration_hints(
    tmp_path, investigation, papers, monkeypatch
) -> None:
    application = make_app(
        tmp_path,
        FakeProvider([]),
        papers,
        investigation=investigation,
    )
    application.service.workspace.save(investigation)

    async with application.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        await application._handle_submission("/staged")
        assert any("Command changed" in card.card_title for card in application.query(TimelineCard))

        await application._handle_submission("/plan")
        assert isinstance(application.screen, DetailScreen)
        await pilot.press("escape")

        papers_command = application.run_worker(application._handle_submission("/papers"))
        await wait_for(pilot, lambda: isinstance(application.screen, PapersScreen))
        listing = application.screen.query_one("#paper-list", SelectionList)
        listing.toggle(investigation.papers[0].paper.id)
        await pilot.press("f")
        await pilot.press("f")
        await pilot.press("down", "i")
        assert isinstance(application.screen, DetailScreen)
        await pilot.press("escape")
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(application.screen, PapersScreen))
        await papers_command.wait()

        await application._handle_submission("/unknown")
        await application._handle_submission("/evidence missing")
        assert any(card.card_title == "Unknown command" for card in application.query(TimelineCard))
        assert any(
            card.card_title == "Evidence not found" for card in application.query(TimelineCard)
        )


@pytest.mark.asyncio
async def test_dossier_consent_sources_ask_export_and_purge(
    tmp_path, investigation, papers, monkeypatch
) -> None:
    application = make_app(
        tmp_path,
        FakeProvider([]),
        papers,
        investigation=investigation,
    )
    workspace = application.service.workspace
    workspace.save(investigation)
    document = EvidenceDocument(
        id="doc-1",
        investigation_id=investigation.id,
        paper_id=investigation.papers[0].paper.id,
        source="fixture",
        evidence_level=EvidenceLevel.ABSTRACT,
        status="fallback",
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
    monkeypatch.setattr(application.service, "ask", lambda value, question: answer)

    async with application.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        await application._handle_submission("/sources")
        await application._handle_submission("/evidence chunk-1")
        await application._handle_submission("/ask What improves coherence?")
        await application._handle_submission("/dossier")
        assert any(
            card.card_title == "Research dossier" for card in application.query(TimelineCard)
        )
        await application._handle_submission("/export")
        assert (tmp_path / ".ragdoll" / "exports" / investigation.id / "dossier.md").exists()

        purge = application.run_worker(application._purge())
        await wait_for(pilot, lambda: isinstance(application.screen, ConfirmScreen))
        await pilot.press("n")
        await purge.wait()
        assert workspace.load_dossier(investigation.id) is not None

        purge = application.run_worker(application._purge())
        await wait_for(pilot, lambda: isinstance(application.screen, ConfirmScreen))
        await pilot.press("y")
        await purge.wait()
        assert workspace.load_dossier(investigation.id) is None


@pytest.mark.asyncio
async def test_dossier_build_failure_and_refresh_paths(
    tmp_path, investigation, papers, monkeypatch
) -> None:
    application = make_app(
        tmp_path,
        FakeProvider([]),
        papers,
        investigation=investigation,
    )
    application.service.workspace.save(investigation)
    built = ResearchDossier(
        title="Dossier",
        evidence_summary="No usable evidence was indexed.",
        sections=[{"title": "Executive summary", "claims": []}],
    )
    updated = investigation.model_copy(update={"dossier_status": DossierStatus.PARTIAL})
    monkeypatch.setattr(
        application.service,
        "build_dossier",
        lambda value: (updated, built, ["abstract fallback"]),
    )

    async with application.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        build = application.run_worker(application._dossier(""))
        await wait_for(pilot, lambda: isinstance(application.screen, ConfirmScreen))
        await pilot.press("y")
        await build.wait()
        assert any(
            card.card_title == "Evidence fallback" for card in application.query(TimelineCard)
        )

        application.service.workspace.save_dossier(investigation.id, built)
        await application._dossier("refresh Missing")
        assert any(
            card.card_title == "Dossier section not found"
            for card in application.query(TimelineCard)
        )

        def fail(value):
            raise ProviderError("bad citations")

        monkeypatch.setattr(application.service, "build_dossier", fail)
        await application._build_dossier()
        assert any(card.card_title == "Dossier failed" for card in application.query(TimelineCard))


@pytest.mark.asyncio
async def test_composer_help_completion_interrupt_and_card_detail(tmp_path, papers) -> None:
    application = make_app(tmp_path, FakeProvider([]), papers)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        composer = application.query_one("#composer", TextArea)
        application.command_history[:] = ["/plan", "/papers"]
        composer.load_text("/pap")
        await pilot.press("tab")
        assert composer.text == "/papers "
        composer.load_text("")
        await pilot.press("up")
        assert composer.text == "/papers"
        await pilot.press("up")
        assert composer.text == "/plan"
        await pilot.press("down")
        assert composer.text == "/papers"
        composer.load_text("pla")
        await pilot.press("ctrl+r")
        assert composer.text == "/plan"
        composer.load_text("/pa")
        await pilot.pause()
        assert application.query_one("#command-menu", Static).display
        composer.load_text("ordinary prompt")
        await pilot.pause()
        assert not application.query_one("#command-menu", Static).display
        composer.load_text("")
        application.action_help()
        assert isinstance(application.screen, DetailScreen)
        await pilot.press("escape")
        composer.load_text("draft")
        application.action_interrupt()
        assert composer.text == ""
        await application.add_card("Expandable", "Summary", "# Details")
        card = list(application.query(TimelineCard))[-1]
        card.focus()
        await pilot.press("enter")
        assert isinstance(application.screen, DetailScreen)
        await pilot.press("escape")
        await pilot.resize_terminal(70, 20)
        await pilot.pause()
        assert application.query_one("#resize-warning", Static).display
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert not application.query_one("#resize-warning", Static).display


@pytest.mark.asyncio
async def test_reduced_motion_cameo_is_transient_and_not_in_timeline(tmp_path, papers) -> None:
    application = make_app(tmp_path, FakeProvider([]), papers)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        cards_before = len(application.query(TimelineCard))
        async with application.activity("searching", "Searching scholarly sources…"):
            await pilot.pause()
            console = Console(width=80, color_system=None)
            visual = cast(Any, application.query_one("#activity", Static).render())
            with console.capture() as capture:
                console.print(visual._renderable)
            rendered = capture.get()
            assert "Searching scholarly sources" in rendered
            assert "● working" in rendered
        await pilot.pause()
        visual = cast(Any, application.query_one("#activity", Static).render())
        assert str(visual) == ""
        assert len(application.query(TimelineCard)) == cards_before


@pytest.mark.asyncio
async def test_animated_cameo_runs_three_frames_once(tmp_path, papers, monkeypatch) -> None:
    application = RagdollApp(tmp_path, Settings(animate=True), FakeProvider([]))
    application.service.openalex = cast(Any, StaticSource(papers))
    observed: list[int] = []

    def capture_cameo(phase, frame, message, *, color=True):
        observed.append(frame)
        return f"{phase}:{frame}:{message}:{color}"

    monkeypatch.setattr("ragdoll.tui.activity_renderable", capture_cameo)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        await application._play_activity_cameo("planning", "Planning…")
        assert observed == [0, 1, 2]
        await pilot.pause(0.3)
        assert observed == [0, 1, 2]


@pytest.mark.asyncio
async def test_activity_shows_result_phases_and_cleans_up_after_animation_failure(
    tmp_path, papers, monkeypatch
) -> None:
    application = make_app(tmp_path, FakeProvider([]), papers)
    observed: list[str] = []

    async def capture_phase(phase, message):
        observed.append(phase)

    monkeypatch.setattr(application, "_play_activity_cameo", capture_phase)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        async with application.activity("planning", "Planning…"):
            pass
        assert observed == ["planning", "success"]

        observed.clear()
        with pytest.raises(ValueError, match="provider failed"):
            async with application.activity("searching", "Searching…"):
                raise ValueError("provider failed")
        assert observed == ["searching", "error"]

        observed.clear()

        async def fail_animation(phase, message):
            observed.append(phase)
            raise RuntimeError("animation failed")

        monkeypatch.setattr(application, "_play_activity_cameo", fail_animation)
        async with application.activity("staging", "Staging…"):
            pass
        await pilot.pause()
        assert observed == ["staging", "success"]
        assert not application._busy
        assert application.query_one("#composer", TextArea).has_focus


@pytest.mark.asyncio
async def test_composer_submission_and_multiline_shortcuts(tmp_path, brief, plan, papers) -> None:
    provider = FakeProvider([InterviewTurn(complete=True), brief, plan])
    application = make_app(tmp_path, provider, papers)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        composer = application.query_one("#composer", TextArea)
        composer.load_text("first line")
        await pilot.press("shift+enter")
        assert "\n" in composer.text
        composer.load_text("video generation")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(application.screen, PlanReviewScreen))
        assert application.investigation is not None
        assert application.command_history == ["video generation"]
        await pilot.press("q")


@pytest.mark.asyncio
async def test_pre_topic_commands_and_command_serialization(tmp_path, papers, monkeypatch) -> None:
    application = make_app(tmp_path, FakeProvider([]), papers)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        await application._handle_submission("/help")
        assert isinstance(application.screen, DetailScreen)
        assert application.investigation is None
        await pilot.press("escape")
        await application._handle_submission("/papers")
        assert application.investigation is None
        assert any(
            card.card_title == "No active investigation" for card in application.query(TimelineCard)
        )

        active = 0
        maximum_active = 0
        events: list[str] = []

        async def slow_submission(text: str) -> None:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            events.append(f"start:{text}")
            await asyncio.sleep(0.02)
            events.append(f"end:{text}")
            active -= 1

        monkeypatch.setattr(application, "_handle_submission", slow_submission)
        await asyncio.gather(
            application._run_submission("one"),
            application._run_submission("two"),
        )
        assert maximum_active == 1
        assert events == ["start:one", "end:one", "start:two", "end:two"]


@pytest.mark.asyncio
async def test_bootstrap_and_pending_commands_cannot_exit(tmp_path, papers, monkeypatch) -> None:
    provider = FakeProvider([InterviewTurn(complete=False, question=clarification())])
    application = make_app(tmp_path, provider, papers, topic="video generation")
    original_save = application.service.workspace.save
    save_started = threading.Event()
    allow_save = threading.Event()

    def delayed_save(*args, **kwargs) -> None:
        if not save_started.is_set():
            save_started.set()
            assert allow_save.wait(timeout=5)
        original_save(*args, **kwargs)

    monkeypatch.setattr(application.service.workspace, "save", delayed_save)
    exit_calls: list[object] = []
    monkeypatch.setattr(application, "exit", lambda value=None: exit_calls.append(value))
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, save_started.is_set)
        composer = application.query_one("#composer", TextArea)
        assert composer.disabled
        application.action_interrupt()
        application.action_quit_empty()
        assert exit_calls == []
        allow_save.set()
        await wait_for(pilot, lambda: isinstance(application.screen, ClarificationScreen))
        application._command_pending = True
        composer.disabled = True
        application.action_interrupt()
        application.action_quit_empty()
        assert exit_calls == []
        application._command_pending = False
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_command_edge_cases_and_app_actions(
    tmp_path, investigation, papers, monkeypatch
) -> None:
    unstaged = investigation.model_copy(
        update={
            "papers": [item.model_copy(update={"staged": False}) for item in investigation.papers]
        }
    )
    application = make_app(
        tmp_path,
        FakeProvider([]),
        papers,
        investigation=unstaged,
    )
    application.service.workspace.save(unstaged)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        composer = application.query_one("#composer", TextArea)

        application._busy = True
        await application._handle_submission("/help")
        application.action_interrupt()
        composer.disabled = True
        application.action_external_editor()
        composer.disabled = False
        application._busy = False

        await application._handle_submission("/ask")
        await application._handle_submission("/evidence")
        await application._handle_submission("/dossier")
        assert any(card.card_title == "Usage" for card in application.query(TimelineCard))
        assert any(
            card.card_title == "Dossier unavailable" for card in application.query(TimelineCard)
        )

        monkeypatch.setattr(
            application.service,
            "ask",
            lambda value, question: (_ for _ in ()).throw(ValueError("no evidence")),
        )
        await application._handle_submission("What is supported?")
        assert any(
            card.card_title == "Could not answer" for card in application.query(TimelineCard)
        )

        assert application.investigation is not None
        application.investigation = application.investigation.model_copy(
            update={"plan": None, "brief": None}
        )
        await application._handle_submission("/plan")
        assert any(
            card.card_title == "Plan unavailable" for card in application.query(TimelineCard)
        )

        composer.load_text("/zz")
        await pilot.pause()
        assert not application.query_one("#command-menu", Static).display

        monkeypatch.setattr(
            "ragdoll.tui.edit_text",
            lambda text: (_ for _ in ()).throw(ExternalEditorError("editor unavailable")),
        )
        monkeypatch.setattr(application, "suspend", lambda: nullcontext())
        composer.load_text("draft")
        application.action_external_editor()
        application.action_interrupt()
        assert composer.text == ""
        application._empty_interrupts = 0
        application.action_interrupt()
        assert application._empty_interrupts == 1

        await application._handle_submission("/help")
        assert isinstance(application.screen, DetailScreen)
        await pilot.press("escape")
        application.action_quit_empty()


def test_commands_mascot_rendering_and_markdown_helpers(investigation) -> None:
    assert parse_command("/ASK why?") == ("ask", "why?")
    assert parse_command("/ask\twhy now?") == ("ask", "why now?")
    assert parse_command("/ask\nwhy now?") == ("ask", "why now?")
    assert parse_command("a plain question") == ("", "a plain question")
    assert migration_hint("stage") == "/stage was replaced in RAGdoll 2.0. Use /papers."
    assert migration_hint("ask") is None
    assert {"plan", "papers", "dossier", "ask", "quit"} <= COMMAND_NAMES
    assert "/papers" in command_help()
    assert "Keyboard" in help_markdown()
    assert pixel_widths() == {11}
    assert pixel_heights() == {6}
    assert {
        cell_len(row) for frames in SPRITE_FRAMES.values() for frame in frames for row in frame
    } == {11}
    assert FRAME_COUNT == 3
    assert set(SPRITE_FRAMES) == {
        "welcome",
        "planning",
        "searching",
        "staging",
        "success",
        "error",
    }
    assert sprite_rows("welcome", 99) == SPRITE_FRAMES["welcome"][-1]
    assert all(
        "\N{BOX DRAWINGS LIGHT DIAGONAL CROSS}" not in row and "X" not in row
        for frames in SPRITE_FRAMES.values()
        for frame in frames
        for row in frame
    )
    assert activity_renderable("success", 20, "Complete", color=False)
    assert mascot_renderable(color=False)
    assert investigation.plan is not None and investigation.brief is not None
    assert investigation.plan.title in plan_markdown(
        investigation.plan, investigation.brief.objective
    )
    assert investigation.papers[0].paper.title in paper_markdown(investigation.papers[0])
    assert "Staged" in papers_markdown(investigation)


def test_external_editor_is_shell_free_and_bounded(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def successful(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        Path(argv[-1]).write_text("revised", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", successful)
    assert edit_text("draft", {"VISUAL": "code --wait"}) == "revised"
    assert captured["argv"][:2] == ["code", "--wait"]
    assert captured["shell"] is False
    with pytest.raises(ExternalEditorError, match="Set VISUAL"):
        edit_text("draft", {})
    with pytest.raises(ExternalEditorError, match="Invalid editor"):
        edit_text("draft", {"EDITOR": "'"})
    with pytest.raises(ExternalEditorError, match="editor limit"):
        edit_text("x" * (1024 * 1024 + 1), {"EDITOR": "false"})

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 2),
    )
    with pytest.raises(ExternalEditorError, match="status 2"):
        edit_text("draft", {"EDITOR": "false"})


@pytest.mark.asyncio
async def test_dossier_preview_marks_metadata_only_papers(tmp_path, investigation, papers) -> None:
    metadata_paper = papers[0].model_copy(update={"abstract": None, "fulltext_candidates": []})
    metadata_item = investigation.papers[0].model_copy(update={"paper": metadata_paper})
    metadata_investigation = investigation.model_copy(update={"papers": [metadata_item]})
    application = make_app(
        tmp_path,
        FakeProvider([]),
        [metadata_paper],
        investigation=metadata_investigation,
    )
    application.service.workspace.save(metadata_investigation)
    async with application.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: application.query_one("#composer", TextArea).has_focus)
        dossier = application.run_worker(application._dossier(""))
        await wait_for(pilot, lambda: isinstance(application.screen, ConfirmScreen))
        assert "metadata only" in application.screen.message
        await pilot.press("n")
        await dossier.wait()


def test_interactive_adapter_requires_tty(tmp_path, monkeypatch) -> None:
    research = InteractiveResearch(
        tmp_path,
        Settings(animate=False),
        FakeProvider([]),
        Console(force_terminal=False),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    with pytest.raises(ValueError, match="requires a TTY"):
        research.start("topic")


def test_cli_version_and_noninteractive_error(monkeypatch) -> None:
    runner = CliRunner()
    version = runner.invoke(cli_app, ["--version"])
    assert version.exit_code == 0
    assert "ragdoll 2.0.1" in version.output
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    result = runner.invoke(cli_app, ["--topic", "video"])
    assert result.exit_code == 2
    assert "requires a TTY" in result.output


def test_shell_commands_init_list_show_and_export(tmp_path, investigation, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    initialized = runner.invoke(cli_app, ["init"])
    assert initialized.exit_code == 0
    workspace = Workspace(tmp_path)
    workspace.save(investigation)

    listed = runner.invoke(cli_app, ["investigations"])
    assert listed.exit_code == 0
    assert investigation.id in listed.output
    shown = runner.invoke(cli_app, ["show", investigation.id])
    assert shown.exit_code == 0
    assert investigation.original_prompt in shown.output
    missing = runner.invoke(cli_app, ["show", "missing"])
    assert missing.exit_code == 2

    for format_name, suffix in (("markdown", "md"), ("bibtex", "bib"), ("json", "json")):
        destination = tmp_path / f"reading-list.{suffix}"
        result = runner.invoke(
            cli_app,
            ["export", investigation.id, "--format", format_name, "--output", str(destination)],
        )
        assert result.exit_code == 0
        assert destination.exists()
    invalid = runner.invoke(cli_app, ["export", investigation.id, "--format", "xml"])
    assert invalid.exit_code == 2


def test_shell_dossier_exports(tmp_path, investigation, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="Metadata only",
        sections=[{"title": "Executive summary", "claims": []}],
    )
    workspace.save_dossier(investigation.id, dossier)
    runner = CliRunner()
    for format_name, suffix in (("dossier", "md"), ("dossier-json", "json")):
        destination = tmp_path / f"dossier.{suffix}"
        result = runner.invoke(
            cli_app,
            ["export", investigation.id, "--format", format_name, "--output", str(destination)],
        )
        assert result.exit_code == 0
        assert destination.exists()

    workspace.purge_evidence(investigation.id)
    missing = runner.invoke(cli_app, ["export", investigation.id, "--format", "dossier"])
    assert missing.exit_code == 2


def test_cli_main_and_resume_delegate_to_tui(tmp_path, investigation, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Workspace(tmp_path).save(investigation)
    calls: list[tuple[str, object]] = []

    class FakeInteractive:
        def __init__(self, root, settings, provider, console=None) -> None:
            calls.append(("init", root))

        def start(self, topic):
            calls.append(("start", topic))
            return investigation

        def resume(self, value):
            calls.append(("resume", value.id))
            return value

    monkeypatch.setattr("ragdoll.cli.InteractiveResearch", FakeInteractive)
    monkeypatch.setattr("ragdoll.cli.make_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr("ragdoll.cli._require_interactive_tty", lambda: None)
    runner = CliRunner()
    assert runner.invoke(cli_app, ["--topic", "video", "--no-animation"]).exit_code == 0
    assert runner.invoke(cli_app, ["resume"]).exit_code == 0
    assert runner.invoke(cli_app, ["resume", investigation.id]).exit_code == 0
    assert ("start", "video") in calls
    assert ("resume", investigation.id) in calls
    missing = runner.invoke(cli_app, ["resume", "missing"])
    assert missing.exit_code == 2


def test_cli_startup_errors_interrupt_and_doctor(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ragdoll.cli._require_interactive_tty", lambda: None)
    runner = CliRunner()

    monkeypatch.setattr(
        "ragdoll.cli.make_provider",
        lambda settings: (_ for _ in ()).throw(ProviderError("unavailable")),
    )
    failed = runner.invoke(cli_app, ["--topic", "video"])
    assert failed.exit_code == 2
    assert "unavailable" in failed.output

    class Interrupted:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self, topic):
            raise KeyboardInterrupt

    monkeypatch.setattr("ragdoll.cli.make_provider", lambda settings: FakeProvider([]))
    monkeypatch.setattr("ragdoll.cli.InteractiveResearch", Interrupted)
    interrupted = runner.invoke(cli_app, ["--topic", "video"])
    assert interrupted.exit_code == 0
    assert "Investigation saved" in interrupted.output

    monkeypatch.setattr(
        "ragdoll.cli.load_settings", lambda *args, **kwargs: Settings(provider="openai")
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    doctor = runner.invoke(cli_app, ["doctor"])
    assert doctor.exit_code == 0
    assert "OPENAI_API_KEY: missing" in doctor.output

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {"models": [{"name": "qwen3:4b"}]}

    monkeypatch.setattr(
        "ragdoll.cli.load_settings", lambda *args, **kwargs: Settings(provider="ollama")
    )
    monkeypatch.setattr("ragdoll.cli.httpx.get", lambda *args, **kwargs: Response())
    healthy = runner.invoke(cli_app, ["doctor"])
    assert "model: available" in healthy.output
    monkeypatch.setattr(
        "ragdoll.cli.httpx.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad response")),
    )
    unhealthy = runner.invoke(cli_app, ["doctor"])
    assert "unreachable" in unhealthy.output
