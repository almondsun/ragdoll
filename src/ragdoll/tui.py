"""Fullscreen conversation-first terminal interface for RAGdoll 2.1."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from rich.console import Group
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Input,
    Label,
    Markdown,
    OptionList,
    SelectionList,
    Static,
    TextArea,
)

from .commands import COMMAND_NAMES, COMMANDS, command_help, migration_hint, parse_command
from .config import Settings
from .domain import (
    ClarificationAnswer,
    ClarificationQuestion,
    DossierStatus,
    Investigation,
    InvestigationStatus,
    RankedPaper,
    ResearchBrief,
    ResearchDossier,
    ResearchPlan,
)
from .editor import ExternalEditorError, edit_text
from .export import export_dossier, export_investigation, render_answer, render_dossier
from .mascot import MascotPhase, activity_renderable, mascot_renderable
from .planning import Planner
from .providers import ModelProvider, ProviderError
from .service import ResearchService
from .synthesis import SECTION_SPECS

BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]
MASCOT_INTERVAL_SECONDS = 0.18
RESULT_HOLD_TICKS = 5


class Composer(TextArea):
    """Multiline composer that submits on Enter and keeps explicit newline shortcuts."""

    _history_index: int | None = None

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            value = self.text.strip()
            if value:
                self.post_message(self.Submitted(value))
            return
        if event.key in {"shift+enter", "ctrl+j"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        app = self.app
        history = getattr(app, "command_history", [])
        if event.key == "tab" and self.text.startswith("/") and " " not in self.text:
            prefix = self.text[1:].casefold()
            match = next((item for item in COMMANDS if item.name.startswith(prefix)), None)
            if match is not None:
                event.prevent_default()
                event.stop()
                completed = f"/{match.name} "
                self.load_text(completed)
                self.cursor_location = (0, len(completed))
            return
        if event.key == "up" and history and "\n" not in self.text:
            event.prevent_default()
            event.stop()
            if self._history_index is None:
                self._history_index = len(history) - 1
            else:
                self._history_index = max(0, self._history_index - 1)
            self.load_text(history[self._history_index])
            self.cursor_location = (0, len(self.text))
            return
        if event.key == "down" and self._history_index is not None:
            event.prevent_default()
            event.stop()
            if self._history_index >= len(history) - 1:
                self._history_index = None
                self.load_text("")
            else:
                self._history_index += 1
                self.load_text(history[self._history_index])
                self.cursor_location = (0, len(self.text))
            return
        if event.key == "ctrl+r" and history:
            event.prevent_default()
            event.stop()
            needle = self.text.casefold()
            match = next((item for item in reversed(history) if needle in item.casefold()), None)
            if match is not None:
                self.load_text(match)
                self.cursor_location = (0, len(match))


class TimelineCard(Static, can_focus=True):
    """Compact transcript entry with an optional full-detail overlay."""

    def __init__(self, title: str, summary: str, details: str = "", *, tone: str = "") -> None:
        self.card_title = title
        self.details = details
        super().__init__(id=None, classes=f"timeline-card {tone}".strip())
        self.update(Group(Text(title, style="bold"), Text(summary)))

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter" and self.details:
            event.stop()
            self.app.push_screen(DetailScreen(self.card_title, self.details))


class DetailScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "close", "Close")]

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.content = content

    def compose(self) -> ComposeResult:
        with Container(classes="dialog detail-dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield VerticalScroll(Markdown(self.content), classes="dialog-body")
            yield Label("Esc close · ↑/↓ scroll", classes="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("y", "confirm", "Confirm"),
        Binding("n", "cancel", "Cancel"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, message: str, confirm_label: str = "Continue") -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Container(classes="dialog confirm-dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield Markdown(self.message, classes="dialog-body")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, variant="warning", id="confirm")
            yield Label("Y confirm · N/Esc cancel", classes="dialog-hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ClarificationScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Save and quit")]

    def __init__(self, question: ClarificationQuestion) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        options = [
            f"{index}. {option.label}\n   [dim]{option.description}[/dim]"
            for index, option in enumerate(self.question.options, 1)
        ]
        options.append("4. Enter my own answer")
        with Container(classes="dialog clarification-dialog"):
            yield Label(self.question.question, classes="dialog-title")
            yield OptionList(*options, id="clarification-options")
            yield Input(placeholder="Type your answer, then press Enter", id="custom-answer")
            yield Label(
                "1-4 or ↑/↓ choose · Enter select · Esc save and quit",
                classes="dialog-hint",
            )

    def on_mount(self) -> None:
        custom = self.query_one("#custom-answer", Input)
        custom.display = False
        self.query_one(OptionList).focus()

    def _select(self, index: int) -> None:
        if 0 <= index < 3:
            option = self.question.options[index]
            self.dismiss(f"{option.label}: {option.description}")
        elif index == 3:
            custom = self.query_one("#custom-answer", Input)
            custom.display = True
            custom.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._select(event.option_index)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        answer = event.value.strip()
        if answer:
            self.dismiss(answer)
        else:
            self.notify("Your answer cannot be empty.", severity="warning")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"1", "2", "3", "4"} and not self.query_one(Input).has_focus:
            event.stop()
            self._select(int(event.key) - 1)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PlanReviewScreen(ModalScreen[str]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("a", "approve", "Approve"),
        Binding("b", "back", "Back"),
        Binding("q", "quit", "Save and quit"),
        Binding("escape", "quit", "Save and quit"),
    ]

    def __init__(self, plan: ResearchPlan, brief: ResearchBrief) -> None:
        super().__init__()
        self.plan = plan
        self.brief = brief

    def compose(self) -> ComposeResult:
        with Container(classes="dialog plan-dialog"):
            yield Label("Review the research plan", classes="dialog-title")
            yield VerticalScroll(
                Markdown(plan_markdown(self.plan, self.brief)), classes="dialog-body"
            )
            yield Input(placeholder="Optional revision request", id="plan-revision")
            with Horizontal(classes="dialog-actions"):
                yield Button("Back", id="back")
                yield Button("Save and quit", id="quit")
                yield Button("Apply edit", id="edit")
                yield Button("Approve search", variant="success", id="approve")
            yield Label("A approve · type a revision and choose Apply edit", classes="dialog-hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id or ""
        if action == "edit":
            request = self.query_one("#plan-revision", Input).value.strip()
            if not request:
                self.notify("Describe the plan change first.", severity="warning")
                return
            self.dismiss(f"edit:{request}")
            return
        self.dismiss(action)

    def action_approve(self) -> None:
        self.dismiss("approve")

    def action_back(self) -> None:
        self.dismiss("back")

    def action_quit(self) -> None:
        self.dismiss("quit")


class PapersScreen(ModalScreen[frozenset[str]]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "done", "Done"),
        Binding("i", "inspect", "Inspect"),
        Binding("f", "filter", "All/Staged"),
    ]

    def __init__(self, investigation: Investigation) -> None:
        super().__init__()
        self.investigation = investigation
        self.staged = {item.paper.id for item in investigation.papers if item.staged}
        self.staged_only = False

    def compose(self) -> ComposeResult:
        with Container(classes="dialog papers-dialog"):
            yield Label("Paper candidates · All", classes="dialog-title", id="papers-title")
            yield SelectionList[str](id="paper-list")
            with Horizontal(classes="dialog-actions"):
                yield Button("All / staged", id="filter")
                yield Button("Inspect", id="inspect")
                yield Button("Done", variant="success", id="done")
            yield Label("Space stage · I inspect · F filter · Esc done", classes="dialog-hint")

    def on_mount(self) -> None:
        self._populate()
        self.query_one(SelectionList).focus()

    def _visible(self) -> Iterator[tuple[int, RankedPaper]]:
        for index, item in enumerate(self.investigation.papers, 1):
            if not self.staged_only or item.paper.id in self.staged:
                yield index, item

    def _populate(self) -> None:
        listing = self.query_one("#paper-list", SelectionList)
        listing.clear_options()
        for index, item in self._visible():
            title = f"{index:>2}. {item.paper.title} ({item.paper.year or '—'}) · {item.score:.3f}"
            listing.add_option((title, item.paper.id, item.paper.id in self.staged))
        mode = "Staged" if self.staged_only else "All"
        self.query_one("#papers-title", Label).update(f"Paper candidates · {mode}")

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        visible_ids = {item.paper.id for _, item in self._visible()}
        self.staged.difference_update(visible_ids)
        self.staged.update(str(value) for value in event.selection_list.selected)

    def _highlighted_item(self) -> RankedPaper | None:
        listing = self.query_one(SelectionList)
        if listing.highlighted is None:
            return None
        option = listing.get_option_at_index(listing.highlighted)
        paper_id = str(option.value)
        return next((item for item in self.investigation.papers if item.paper.id == paper_id), None)

    def action_inspect(self) -> None:
        item = self._highlighted_item()
        if item is not None:
            self.app.push_screen(DetailScreen(item.paper.title, paper_markdown(item)))

    def action_filter(self) -> None:
        self.staged_only = not self.staged_only
        self._populate()

    def action_done(self) -> None:
        self.dismiss(frozenset(self.staged))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action = event.button.id
        if action == "filter":
            self.action_filter()
        elif action == "inspect":
            self.action_inspect()
        elif action == "done":
            self.action_done()


class RagdollApp(App[Investigation | None]):
    """The v2 TUI; all research operations remain in Planner and ResearchService."""

    CSS = """
    Screen { background: transparent; color: auto; }
    #header { height: 3; padding: 0 2; border-bottom: solid #2aa198; }
    #brand { width: 1fr; content-align: left middle; color: #2aa198; text-style: bold; }
    #context { width: auto; content-align: right middle; color: $text-muted; }
    #timeline { height: 1fr; padding: 1 2; scrollbar-color: #2aa198; }
    .timeline-card {
        height: auto;
        min-height: 3;
        margin: 0 0 1 0;
        padding: 1 2;
        border-left: thick #2aa198;
    }
    .timeline-card:focus { background: $boost; border-left: thick #b87333; }
    .user { border-left: thick #b87333; }
    .warning { border-left: thick $warning; }
    .error { border-left: thick $error; }
    .success { border-left: thick $success; }
    #activity { height: 2; margin: 0 2; color: $text-muted; }
    #command-menu {
        height: auto;
        max-height: 6;
        margin: 0 2;
        padding: 0 1;
        border: round #2aa198;
        display: none;
    }
    #composer { height: 5; margin: 0 2; border: round #2aa198; background: transparent; }
    #composer:focus { border: round #b87333; }
    #footer { height: 2; padding: 0 2; color: $text-muted; }
    #resize-warning {
        display: none;
        layer: overlay;
        width: 100%;
        height: 100%;
        content-align: center middle;
        text-align: center;
        background: $surface;
        color: $warning;
        text-style: bold;
    }
    .dialog {
        width: 82%;
        height: auto;
        max-height: 88%;
        padding: 1 2;
        border: round #2aa198;
        background: $surface;
    }
    .detail-dialog { height: 86%; }
    .plan-dialog { height: 88%; }
    .papers-dialog { height: 86%; }
    .clarification-dialog { min-height: 24; }
    .confirm-dialog { width: 64%; }
    .dialog-title { height: auto; padding: 0 0 1 0; text-style: bold; color: #b87333; }
    .dialog-body { height: 1fr; }
    .dialog-actions { height: 3; align-horizontal: right; }
    .dialog-actions Button { margin-left: 1; }
    .dialog-hint { height: 1; color: $text-muted; }
    #custom-answer { display: none; margin-top: 1; }
    #plan-revision { margin: 1 0; }
    #paper-list { height: 1fr; }
    """

    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("ctrl+l", "refresh", "Redraw", show=False),
        Binding("ctrl+g", "external_editor", "Editor", show=False),
        Binding("ctrl+c", "interrupt", "Clear / exit", show=False),
        Binding("ctrl+d", "quit_empty", "Exit", show=False),
        Binding("question_mark", "help", "Help", show=False),
    ]

    def __init__(
        self,
        root: Path,
        settings: Settings,
        provider: ModelProvider,
        *,
        topic: str | None = None,
        investigation: Investigation | None = None,
        service: ResearchService | None = None,
        planner: Planner | None = None,
        demo_mode: bool = False,
    ) -> None:
        super().__init__()
        self.root = root
        self.settings = settings
        self.provider = provider
        self.service = service or ResearchService(root, settings, provider)
        self.planner = planner or Planner(provider)
        self.demo_mode = demo_mode
        self.initial_topic = topic
        self.investigation = investigation
        self._busy = False
        self._mascot_state: MascotPhase = "idle"
        self._mascot_message = "Ready"
        self._mascot_frame = 0
        self._mascot_ticks = 0
        self._mascot_result_ticks = 0
        self._mascot_timer: Timer | None = None
        self._empty_interrupts = 0
        self._command_pending = False
        self._workflow_pending = bool(topic or investigation is not None)
        self._command_lock = asyncio.Lock()
        self.command_history: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("RAGdoll", id="brand")
            yield Static("new investigation", id="context")
        yield VerticalScroll(id="timeline")
        yield Static("", id="activity")
        yield Static("", id="command-menu")
        yield Composer(
            id="composer",
            placeholder=(
                "Offline sample · inspect with /plan /papers /dossier /sources /evidence"
                if self.demo_mode
                else "Describe a research topic · / for commands · ? for help"
            ),
            soft_wrap=True,
            show_line_numbers=False,
            compact=True,
        )
        yield Static("Enter send · Shift+Enter newline · Ctrl+G editor", id="footer")
        yield Static(
            "RAGdoll needs at least an 80 x 24 terminal.\nResize the window to continue.",
            id="resize-warning",
        )

    def on_mount(self) -> None:
        self.title = "RAGdoll"
        if self.initial_topic or self.investigation is not None:
            self.query_one(Composer).disabled = True
        self._render_mascot()
        self._mascot_timer = self.set_interval(
            MASCOT_INTERVAL_SECONDS, self._tick_mascot, name="m2-mascot"
        )
        self.run_worker(self._bootstrap(), group="workflow", exclusive=True)

    def on_unmount(self) -> None:
        if self._mascot_timer is not None:
            self._mascot_timer.stop()
            self._mascot_timer = None

    async def _bootstrap(self) -> None:
        try:
            await self._show_splash()
            if self.demo_mode:
                await self.add_card(
                    "Offline sample",
                    "Bundled synthetic evidence · no model, network, or API key",
                    (
                        "This temporary workspace exercises the real RAGdoll interface and "
                        "inspection paths. Generated content is clearly labeled sample data, "
                        "and the workspace is discarded when the demo exits."
                    ),
                    "system",
                )
            else:
                details = self.service.inference_details()
                await self.add_card(
                    "Inference destination",
                    (
                        f"{details['provider']} · {details['model']} · "
                        f"{details['endpoint']} · {details['transport']}"
                    ),
                    (
                        "Research topics, clarification answers, briefs/plans, candidate titles "
                        "and abstracts are sent for planning and ranking. Evidence passages are "
                        "sent only after the separate dossier confirmation."
                    ),
                    "warning" if details["transport"] == "remote" else "system",
                )
            if self.investigation is not None:
                await self._resume_flow()
            elif self.initial_topic:
                await self._start_flow(self.initial_topic)
        finally:
            self._workflow_pending = False
            composers = self.query(Composer)
            if composers:
                composer = composers.first()
                composer.disabled = self._busy or self._command_pending
                if not composer.disabled:
                    composer.focus()

    async def _show_splash(self) -> None:
        color = not bool(os.getenv("NO_COLOR"))
        card = Static(
            mascot_renderable(color=color),
            id="splash",
            classes="timeline-card splash",
        )
        timeline = self.query_one("#timeline", VerticalScroll)
        await timeline.mount(card)
        timeline.scroll_end(animate=False)

    async def add_card(self, title: str, summary: str, details: str = "", tone: str = "") -> None:
        timeline = self.query_one("#timeline", VerticalScroll)
        await timeline.mount(TimelineCard(title, summary, details, tone=tone))
        timeline.scroll_end(animate=False)

    @asynccontextmanager
    async def activity(self, state: str, message: str) -> AsyncIterator[None]:
        self._busy = True
        self.query_one(Composer).disabled = True
        self._set_mascot(self._coerce_mascot_phase(state), message)
        operation_failed = False
        try:
            yield
        except BaseException:
            operation_failed = True
            raise
        finally:
            try:
                result_phase: MascotPhase = "error" if operation_failed else "success"
                result_message = "Operation stopped" if operation_failed else "Phase complete"
                self._set_mascot(result_phase, result_message, hold_ticks=RESULT_HOLD_TICKS)
            finally:
                self._busy = False
                composers = self.query(Composer)
                if composers:
                    composer = composers.first()
                    composer.disabled = self._command_pending or self._workflow_pending
                    if not composer.disabled:
                        composer.focus()
                self._update_status()

    @staticmethod
    def _coerce_mascot_phase(state: str) -> MascotPhase:
        if state == "searching":
            return "searching"
        if state == "staging":
            return "staging"
        return "planning"

    def _set_mascot(self, phase: MascotPhase, message: str, *, hold_ticks: int = 0) -> None:
        self._mascot_state = phase
        self._mascot_message = message
        self._mascot_frame = 0
        self._mascot_ticks = 0
        self._mascot_result_ticks = hold_ticks
        self._render_mascot()

    def _tick_mascot(self) -> None:
        if self._mascot_result_ticks:
            self._mascot_result_ticks -= 1
            if not self._mascot_result_ticks:
                self._set_mascot("idle", "Ready")
                return
        if not self.settings.animate:
            return
        self._mascot_ticks += 1
        if self._mascot_state == "idle" and self._mascot_ticks % 2:
            return
        self._mascot_frame += 1
        self._render_mascot()

    def _render_mascot(self) -> None:
        activity = self.query("#activity")
        if not activity:
            return
        with suppress(Exception):
            activity.first(Static).update(
                activity_renderable(
                    self._mascot_state,
                    self._mascot_frame,
                    self._mascot_message,
                    color=not bool(os.getenv("NO_COLOR")),
                )
            )

    async def _start_flow(self, topic: str) -> None:
        topic = topic.strip()
        if not topic:
            self.notify("A research topic is required.", severity="warning")
            return
        await self.add_card("You", topic, tone="user")
        now = datetime.now(UTC)
        self.investigation = Investigation(
            id=uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            status=InvestigationStatus.INTERVIEW,
            original_prompt=topic,
        )
        await asyncio.to_thread(self.service.workspace.save, self.investigation, "created")
        await self._interview_flow()

    async def _resume_flow(self) -> None:
        assert self.investigation is not None
        await self.add_card("Resumed investigation", self.investigation.original_prompt)
        if self.investigation.status == InvestigationStatus.INTERVIEW:
            await self._interview_flow()
        elif self.investigation.status == InvestigationStatus.PLAN_REVIEW:
            await self._plan_review_flow()
        elif self.investigation.status == InvestigationStatus.SEARCHING:
            await self._execute_search("Resuming approved scholarly search…")
        else:
            await self._collection_ready()

    async def _interview_flow(self) -> None:
        assert self.investigation is not None
        while True:
            async with self.activity("planning", "Finding the next pivotal question…"):
                question = await asyncio.to_thread(
                    self.planner.next_question,
                    self.investigation.original_prompt,
                    self.investigation.answers,
                )
            if question is None:
                break
            answer_text = await self.push_screen_wait(ClarificationScreen(question))
            if answer_text is None:
                self.exit(self.investigation)
                return
            await self.add_card(question.question, answer_text)
            answer = ClarificationAnswer(
                question_id=question.id,
                question=question.question,
                answer=answer_text,
                option_labels=[option.label for option in question.options],
            )
            self.investigation = self.investigation.model_copy(
                update={
                    "answers": [*self.investigation.answers, answer],
                    "updated_at": datetime.now(UTC),
                }
            )
            await asyncio.to_thread(
                self.service.workspace.save, self.investigation, "clarification_answered"
            )
        async with self.activity("planning", "Compiling the research brief and plan…"):
            brief = await asyncio.to_thread(
                self.planner.build_brief,
                self.investigation.original_prompt,
                self.investigation.answers,
            )
            plan = await asyncio.to_thread(self.planner.build_plan, brief)
        self.investigation = self.investigation.model_copy(
            update={
                "brief": brief,
                "plan": plan,
                "status": InvestigationStatus.PLAN_REVIEW,
                "updated_at": datetime.now(UTC),
            }
        )
        await asyncio.to_thread(self.service.workspace.save, self.investigation, "plan_created")
        await self._plan_review_flow()

    async def _plan_review_flow(self) -> None:
        assert self.investigation is not None
        assert self.investigation.brief is not None and self.investigation.plan is not None
        while True:
            plan = self.investigation.plan
            brief = self.investigation.brief
            action = await self.push_screen_wait(PlanReviewScreen(plan, brief))
            if action == "approve":
                await asyncio.to_thread(self.service.approve_plan, self.investigation)
                await self.add_card(
                    "Research plan approved",
                    f"{plan.title} · {len(plan.query_families)} query families",
                    plan_markdown(plan, brief),
                    "success",
                )
                await self._execute_search("Searching and ranking scholarly works…")
                return
            if action.startswith("edit:"):
                request = action.removeprefix("edit:")
                async with self.activity("planning", "Revising the investigation plan…"):
                    revised = await asyncio.to_thread(
                        self.planner.revise_plan,
                        self.investigation.brief,
                        plan,
                        request,
                    )
                self.investigation = self.investigation.model_copy(
                    update={"plan": revised, "updated_at": datetime.now(UTC)}
                )
                await asyncio.to_thread(
                    self.service.workspace.save, self.investigation, "plan_revised"
                )
                await self.add_card("Plan revised", request)
            elif action == "back" and self.investigation.answers:
                self.investigation = self.investigation.model_copy(
                    update={
                        "answers": self.investigation.answers[:-1],
                        "brief": None,
                        "plan": None,
                        "status": InvestigationStatus.INTERVIEW,
                    }
                )
                await asyncio.to_thread(
                    self.service.workspace.save, self.investigation, "interview_reopened"
                )
                await self._interview_flow()
                return
            elif action == "quit":
                self.exit(self.investigation)
                return

    async def _execute_search(self, message: str) -> None:
        assert self.investigation is not None
        try:
            async with self.activity("searching", message):
                self.investigation, warnings = await asyncio.to_thread(
                    self.service.execute, self.investigation
                )
            for warning in warnings:
                await self.add_card("Partial coverage", warning, tone="warning")
            await self._collection_ready()
        except (ValueError, ProviderError) as error:
            await self.add_card("Search failed", str(error), tone="error")

    async def _collection_ready(self) -> None:
        assert self.investigation is not None
        staged = sum(item.staged for item in self.investigation.papers)
        await self.add_card(
            "Paper collection",
            f"{len(self.investigation.papers)} candidates · {staged} staged · Enter to inspect",
            papers_markdown(self.investigation),
        )
        self._update_status()
        self.query_one(Composer).focus()

    def _update_status(self) -> None:
        if self.investigation is None:
            return
        staged = sum(item.staged for item in self.investigation.papers)
        evidence = len(self.service.workspace.list_documents(self.investigation.id))
        destination = "offline demo" if self.demo_mode else self.settings.provider
        self.query_one("#context", Static).update(f"{self.investigation.status} · {destination}")
        self.query_one("#footer", Static).update(
            f"{staged} staged · {evidence} evidence · Enter send · / commands · ? help"
        )
        self.title = f"RAGdoll · {self.investigation.original_prompt[:40]}"

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        if self._command_pending or self._workflow_pending or self._busy:
            return
        composer = self.query_one(Composer)
        composer.load_text("")
        composer.disabled = True
        self._command_pending = True
        self.command_history.append(event.value)
        self._empty_interrupts = 0
        self.run_worker(self._run_submission(event.value), group="command")

    async def _run_submission(self, text: str) -> None:
        async with self._command_lock:
            try:
                await self._handle_submission(text)
            finally:
                self._command_pending = False
                composers = self.query(Composer)
                if composers:
                    composer = composers.first()
                    composer.disabled = self._busy or self._workflow_pending
                    if not composer.disabled:
                        composer.focus()

    async def _handle_submission(self, text: str) -> None:
        if self._busy:
            return
        name, argument = parse_command(text)
        if self.demo_mode and (
            not name
            or name in {"ask", "purge"}
            or (name == "dossier" and argument.casefold().startswith("refresh"))
        ):
            await self.add_card(
                "Offline sample is read-only",
                "Use /plan, /papers, /dossier, /sources, or /evidence demo-chunk-1.",
                tone="warning",
            )
            return
        if self.investigation is None:
            if not name:
                await self._start_flow(argument)
            elif name == "help":
                self.push_screen(DetailScreen("RAGdoll help", help_markdown()))
            elif name == "quit":
                self.exit(None)
            else:
                hint = migration_hint(name)
                message = hint or f"Start an investigation before using /{name}."
                await self.add_card("No active investigation", message, tone="warning")
            return
        if not name:
            await self.add_card("You", argument, tone="user")
            await self._ask(argument)
            return
        hint = migration_hint(name)
        if hint:
            await self.add_card("Command changed in 2.0", hint, tone="warning")
            return
        if name not in COMMAND_NAMES:
            await self.add_card(
                "Unknown command", f"/{name} is not available. Use /help.", tone="error"
            )
            return
        if name == "quit":
            self.exit(self.investigation)
        elif name == "help":
            self.push_screen(DetailScreen("RAGdoll help", help_markdown()))
        elif name == "plan":
            await self._show_plan()
        elif name == "papers":
            await self._show_papers()
        elif name == "ask":
            if not argument:
                await self.add_card("Usage", "`/ask QUESTION`", tone="warning")
            else:
                await self.add_card("You", argument, tone="user")
                await self._ask(argument)
        elif name == "evidence":
            await self._show_evidence(argument)
        elif name == "sources":
            await self._show_sources()
        elif name == "export":
            await self._export_all()
        elif name == "purge":
            await self._purge()
        elif name == "dossier":
            await self._dossier(argument)

    async def _show_plan(self) -> None:
        assert self.investigation is not None
        if self.investigation.plan is None:
            await self.add_card(
                "Plan unavailable", "This investigation has no plan yet.", tone="warning"
            )
            return
        brief = self.investigation.brief
        self.push_screen(
            DetailScreen("Research plan", plan_markdown(self.investigation.plan, brief))
        )

    async def _show_papers(self) -> None:
        assert self.investigation is not None
        staged = await self.push_screen_wait(PapersScreen(self.investigation))
        current = {item.paper.id for item in self.investigation.papers if item.staged}
        if self.demo_mode:
            await self.add_card(
                "Offline sample unchanged",
                "Paper staging changes are discarded in demo mode.",
                papers_markdown(self.investigation),
                "system",
            )
            return
        for paper_id in sorted(current ^ set(staged)):
            self.investigation = await asyncio.to_thread(
                self.service.set_staged,
                self.investigation,
                paper_id,
                paper_id in staged,
            )
        await self.add_card(
            "Paper staging updated",
            f"{len(staged)} of {len(self.investigation.papers)} papers staged.",
            papers_markdown(self.investigation),
            "success",
        )
        self._update_status()

    async def _ask(self, question: str) -> None:
        assert self.investigation is not None
        try:
            async with self.activity("planning", "Retrieving grounded evidence…"):
                answer = await asyncio.to_thread(self.service.ask, self.investigation, question)
            chunk_ids = [item for claim in answer.claims for item in claim.chunk_ids]
            rendered = render_answer(answer, self.service.workspace.chunks(chunk_ids))
            await self.add_card(
                "Grounded answer",
                answer.explanation,
                rendered,
                "success" if not answer.insufficient_evidence else "warning",
            )
        except (ValueError, ProviderError) as error:
            await self.add_card("Could not answer", str(error), tone="error")

    async def _show_evidence(self, citation: str) -> None:
        if not citation:
            await self.add_card("Usage", "`/evidence CITATION`", tone="warning")
            return
        chunk = self.service.workspace.chunks([citation]).get(citation)
        if chunk is None:
            await self.add_card("Evidence not found", citation, tone="error")
            return
        details = (
            f"# {chunk.paper_id} — {chunk.locator}\n\n"
            f"**Evidence level:** {chunk.evidence_level}\n\n{chunk.text}"
        )
        await self.add_card("Evidence passage", f"{chunk.paper_id} · {chunk.locator}", details)

    async def _show_sources(self) -> None:
        assert self.investigation is not None
        documents = self.service.workspace.list_documents(self.investigation.id)
        rows = ["| Paper | Evidence | Status | Pages | Source |", "|---|---|---|---:|---|"]
        for document in documents:
            rows.append(
                f"| {document.paper_id} | {document.evidence_level} | {document.status} | "
                f"{document.page_count or '—'} | {document.source} |"
            )
        await self.add_card(
            "Evidence sources",
            f"{len(documents)} acquired document records.",
            "\n".join(rows),
        )

    async def _export_all(self) -> None:
        assert self.investigation is not None
        directory = self.root / ".ragdoll" / "exports" / self.investigation.id
        for format_name, suffix in (("markdown", "md"), ("bibtex", "bib"), ("json", "json")):
            await asyncio.to_thread(
                export_investigation,
                self.investigation,
                directory / f"reading-list.{suffix}",
                format_name,
            )
        dossier = self.service.current_dossier(self.investigation)
        if dossier:
            chunk_ids = [
                item
                for section in dossier.sections
                for claim in section.claims
                for item in claim.chunk_ids
            ]
            chunks = self.service.workspace.chunks(chunk_ids)
            await asyncio.to_thread(
                export_dossier,
                dossier,
                self.investigation,
                chunks,
                directory / "dossier.md",
                "markdown",
            )
            await asyncio.to_thread(
                export_dossier,
                dossier,
                self.investigation,
                chunks,
                directory / "dossier.json",
                "json",
            )
        await self.add_card("Export complete", str(directory), tone="success")

    async def _purge(self) -> None:
        assert self.investigation is not None
        confirmed = await self.push_screen_wait(
            ConfirmScreen(
                "Delete local evidence?",
                "This removes cached documents, indexed passages, grounded answers, and the "
                "dossier. "
                "The paper collection and research plan remain.",
                "Delete evidence",
            )
        )
        if not confirmed:
            return
        try:
            self.investigation = await asyncio.to_thread(
                self.service.purge_evidence, self.investigation
            )
            await self.add_card(
                "Evidence deleted",
                "The local evidence cache and dossier were removed.",
                tone="success",
            )
            self._update_status()
        except OSError as error:
            await self.add_card("Evidence purge failed", str(error), tone="error")

    async def _dossier(self, argument: str) -> None:
        assert self.investigation is not None
        existing = self.service.current_dossier(self.investigation)
        command, _, requested = argument.partition(" ")
        if existing and command.casefold() == "refresh":
            await self._refresh_dossier(existing, requested.strip() or "Open questions")
            return
        if existing:
            if (
                self.investigation.dossier_status == DossierStatus.PARTIAL
                and len(existing.sections) < 7
            ):
                resume = await self.push_screen_wait(
                    ConfirmScreen("Resume dossier?", "The dossier is incomplete.", "Resume")
                )
                if resume:
                    await self._build_dossier()
                    return
            await self._show_dossier(existing)
            return
        staged = [item for item in self.investigation.papers if item.staged]
        if not staged:
            await self.add_card(
                "Dossier unavailable", "Stage at least one paper first.", tone="warning"
            )
            return
        limit = self.settings.dossier_paper_limit
        preview_rows = []
        for item in staged[:limit]:
            if item.paper.fulltext_candidates:
                level = "open full text"
            elif item.paper.abstract:
                level = "abstract fallback"
            else:
                level = "metadata only"
            preview_rows.append(f"- {item.paper.title} ({level})")
        preview = "\n".join(preview_rows)
        self.investigation = await asyncio.to_thread(
            self.service.mark_dossier_awaiting_approval, self.investigation
        )
        details = self.service.inference_details()
        data_effect = (
            f"Selected evidence passages will be sent to **{details['provider']}** model "
            f"`{details['model']}` at `{details['endpoint']}` ({details['transport']})."
        )
        confirmed = await self.push_screen_wait(
            ConfirmScreen(
                "Acquire dossier evidence?",
                "RAGdoll will download and parse available open full text. "
                f"{data_effect}\n\n{preview}",
                "Acquire and build",
            )
        )
        if confirmed:
            await asyncio.to_thread(self.service.approve_evidence, self.investigation)
            await self._build_dossier()
        else:
            await self.add_card("Dossier cancelled", "No documents were downloaded.")

    async def _refresh_dossier(self, existing: ResearchDossier, title: str) -> None:
        assert self.investigation is not None
        if not self.service.workspace.remove_dossier_section(self.investigation.id, title):
            canonical = next(
                (name for name, _ in SECTION_SPECS if name.casefold() == title.casefold()), None
            )
            existing_titles = {section.title.casefold() for section in existing.sections}
            if canonical is None or canonical.casefold() in existing_titles:
                await self.add_card("Dossier section not found", title, tone="error")
                return
        await self._build_dossier()

    async def _build_dossier(self) -> None:
        assert self.investigation is not None
        try:
            async with self.activity("staging", "Acquiring, indexing, and synthesizing evidence…"):
                self.investigation, dossier, warnings = await asyncio.to_thread(
                    self.service.build_dossier, self.investigation
                )
            for warning in warnings:
                await self.add_card("Evidence fallback", warning, tone="warning")
            await self._show_dossier(dossier)
            self._update_status()
        except (ValueError, ProviderError) as error:
            await self.add_card("Dossier failed", str(error), tone="error")
            investigation = self.investigation
            assert investigation is not None
            self.investigation = self.service.workspace.load(investigation.id)

    async def _show_dossier(self, dossier: ResearchDossier) -> None:
        assert self.investigation is not None
        chunk_ids = [
            item
            for section in dossier.sections
            for claim in section.claims
            for item in claim.chunk_ids
        ]
        rendered = render_dossier(
            dossier, self.investigation, self.service.workspace.chunks(chunk_ids)
        )
        claims = sum(len(section.claims) for section in dossier.sections)
        await self.add_card(
            "Research dossier",
            f"{len(dossier.sections)} sections · {claims} cited claims · Enter to read",
            rendered,
            "success",
        )

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "composer":
            return
        text = event.text_area.text.lstrip()
        menu = self.query_one("#command-menu", Static)
        if not text.startswith("/") or " " in text:
            menu.display = False
            return
        prefix = text[1:].casefold()
        matches = [item for item in COMMANDS if item.name.startswith(prefix)][:4]
        if not matches:
            menu.display = False
            return
        menu.update(
            "\n".join(
                f"[bold]/{item.name}[/bold]  [dim]{item.description}[/dim]" for item in matches
            )
        )
        menu.display = True

    def on_resize(self, event: events.Resize) -> None:
        warning = self.query_one("#resize-warning", Static)
        warning.display = event.size.width < 80 or event.size.height < 24

    def action_external_editor(self) -> None:
        composer = self.query_one(Composer)
        if composer.disabled:
            return
        try:
            with self.suspend():
                revised = edit_text(composer.text)
            composer.load_text(revised)
            composer.focus()
        except ExternalEditorError as error:
            self.notify(str(error), severity="error")

    def action_interrupt(self) -> None:
        composer = self.query_one(Composer)
        if self._busy or self._command_pending or self._workflow_pending:
            self.notify("The current operation will finish before RAGdoll can exit.")
            return
        if composer.text:
            composer.load_text("")
            self._empty_interrupts = 1
            return
        if self._empty_interrupts:
            self.exit(self.investigation)
        else:
            self._empty_interrupts = 1
            self.notify("Press Ctrl+C again to save and exit.")

    def action_quit_empty(self) -> None:
        if self._busy or self._command_pending or self._workflow_pending:
            self.notify("The current operation will finish before RAGdoll can exit.")
            return
        if not self.query_one(Composer).text:
            self.exit(self.investigation)

    def action_help(self) -> None:
        composer = self.query_one(Composer)
        if not composer.text and not isinstance(self.screen, ModalScreen):
            self.push_screen(DetailScreen("RAGdoll help", help_markdown()))


def plan_markdown(plan: ResearchPlan, brief: ResearchBrief | str | None) -> str:
    axes = "\n".join(f"- {axis}" for axis in plan.investigation_axes)
    queries = "\n".join(f"- `{query.query}` — {query.rationale}" for query in plan.query_families)
    discovery = ", ".join(plan.sources)
    enrichment = ", ".join(plan.metadata_sources) or "none"
    objective = brief.objective if isinstance(brief, ResearchBrief) else (brief or "")
    if isinstance(brief, ResearchBrief):
        date_range = f"{brief.date_from or 'unbounded'} to {brief.date_to or 'unbounded'}"
    else:
        date_range = "unbounded"
    return (
        f"# {plan.title}\n\n**Objective:** {objective}\n\n"
        f"**Date range:** {date_range}  \n**Discovery sources:** {discovery}  \n"
        f"**Metadata enrichment:** {enrichment}\n\n"
        f"## Axes\n{axes}\n\n## Queries\n{queries}"
    )


def paper_markdown(item: RankedPaper) -> str:
    paper = item.paper
    authors = ", ".join(paper.authors) or "Unknown"
    evidence = "abstract available" if paper.abstract else "metadata only"
    return (
        f"# {paper.title}\n\n**Authors:** {authors}  \n**Evidence:** {evidence}  \n"
        f"**Score:** {item.score:.3f}  \n**Why:** {item.rationale}\n\n{paper.abstract or ''}"
    )


def papers_markdown(investigation: Investigation) -> str:
    rows = ["| # | Staged | Paper | Year | Score |", "|---:|:---:|---|---:|---:|"]
    for index, item in enumerate(investigation.papers, 1):
        staged = "●" if item.staged else ""
        rows.append(
            f"| {index} | {staged} | {item.paper.title} | {item.paper.year or '—'} | "
            f"{item.score:.3f} |"
        )
    return "\n".join(rows)


def help_markdown() -> str:
    return (
        command_help()
        + "\n\n# Keyboard\n\n"
        + "- `Enter` send · `Shift+Enter`/`Ctrl+J` newline\n"
        + "- `Ctrl+G` external editor · `Ctrl+L` redraw\n"
        + "- `Esc` close overlays · `Ctrl+C` clear, then exit · `Ctrl+D` exit\n"
        + "- Focus a timeline card and press `Enter` to inspect its full details.\n"
    )
