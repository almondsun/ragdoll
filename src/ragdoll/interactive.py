"""Conversational terminal session."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .config import Settings
from .domain import (
    ClarificationAnswer,
    ClarificationQuestion,
    DossierStatus,
    Investigation,
    InvestigationStatus,
    ResearchPlan,
)
from .export import export_dossier, export_investigation, render_answer, render_dossier
from .mascot import Mascot
from .planning import Planner
from .providers import ModelProvider, ProviderError
from .service import ResearchService
from .synthesis import SECTION_SPECS


class InteractiveResearch:
    def __init__(
        self,
        root: Path,
        settings: Settings,
        provider: ModelProvider,
        console: Console | None = None,
        session: PromptSession[str] | None = None,
    ) -> None:
        self.root = root
        self.console = console or Console()
        self.session = session or PromptSession(history=InMemoryHistory())
        self.settings = settings
        self.provider = provider
        self.planner = Planner(provider)
        self.service = ResearchService(root, settings, provider)
        self.mascot = Mascot(self.console, settings.animate)

    def start(self, prompt: str | None = None) -> Investigation:
        self.mascot.welcome()
        original = prompt or self.session.prompt("What do you want to investigate?\n> ").strip()
        if not original:
            raise ValueError("a research topic is required")
        now = datetime.now(UTC)
        investigation = Investigation(
            id=uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            status=InvestigationStatus.INTERVIEW,
            original_prompt=original,
        )
        self.service.workspace.save(investigation, "created")
        return self._interview(investigation)

    def resume(self, investigation: Investigation) -> Investigation:
        self.mascot.welcome()
        if investigation.status == InvestigationStatus.INTERVIEW:
            return self._interview(investigation)
        if investigation.status == InvestigationStatus.PLAN_REVIEW:
            return self._review_plan(investigation)
        if investigation.status == InvestigationStatus.SEARCHING:
            with self.mascot.activity("searching", "Resuming approved scholarly search…"):
                investigation, warnings = self.service.execute(investigation)
            for warning in warnings:
                self.console.print(f"[yellow]Partial coverage: {warning}[/yellow]")
        return self._review_collection(investigation)

    def _interview(self, investigation: Investigation) -> Investigation:
        while True:
            with self.mascot.activity("planning", "Finding the next pivotal question…"):
                question = self.planner.next_question(
                    investigation.original_prompt, investigation.answers
                )
            if question is None:
                break
            answer = self._ask(question)
            answers = [*investigation.answers, answer]
            investigation = investigation.model_copy(
                update={"answers": answers, "updated_at": datetime.now(UTC)}
            )
            self.service.workspace.save(investigation, "clarification_answered")
        with self.mascot.activity("planning", "Compiling the research brief and plan…"):
            brief = self.planner.build_brief(investigation.original_prompt, investigation.answers)
            plan = self.planner.build_plan(brief)
        investigation = investigation.model_copy(
            update={
                "brief": brief,
                "plan": plan,
                "status": InvestigationStatus.PLAN_REVIEW,
                "updated_at": datetime.now(UTC),
            }
        )
        self.service.workspace.save(investigation, "plan_created")
        return self._review_plan(investigation)

    def _ask(self, question: ClarificationQuestion) -> ClarificationAnswer:
        self.console.print(f"\n[bold]{question.question}[/bold]\n")
        for index, option in enumerate(question.options, 1):
            self.console.print(f"  [cyan]{index}.[/cyan] {option.label}")
            self.console.print(f"     [dim]{option.description}[/dim]")
        self.console.print("  [cyan]4.[/cyan] Enter my own answer\n")
        while True:
            choice = self.session.prompt("Select [1-4]: ").strip()
            if choice in {"1", "2", "3"}:
                option = question.options[int(choice) - 1]
                answer = f"{option.label}: {option.description}"
                break
            if choice == "4":
                answer = self.session.prompt("Your answer: ").strip()
                if answer:
                    break
            self.console.print("[yellow]Choose 1, 2, 3, or 4 and provide non-empty text.[/yellow]")
        return ClarificationAnswer(
            question_id=question.id,
            question=question.question,
            answer=answer,
            option_labels=[option.label for option in question.options],
        )

    def _review_plan(self, investigation: Investigation) -> Investigation:
        assert investigation.brief is not None and investigation.plan is not None
        while True:
            self._print_plan(investigation.plan, investigation.brief.objective)
            action = self.session.prompt("[A]pprove  [E]dit  [B]ack  [Q]uit: ").strip().lower()
            if action in {"a", "approve"}:
                with self.mascot.activity("searching", "Searching and ranking scholarly works…"):
                    investigation, warnings = self.service.execute(investigation)
                for warning in warnings:
                    self.console.print(f"[yellow]Partial coverage: {warning}[/yellow]")
                return self._review_collection(investigation)
            if action in {"e", "edit"}:
                request = self.session.prompt("Describe the plan change: ").strip()
                if request:
                    brief = investigation.brief
                    current_plan = investigation.plan
                    assert brief is not None and current_plan is not None
                    with self.mascot.activity("planning", "Revising the investigation plan…"):
                        plan = self.planner.revise_plan(brief, current_plan, request)
                    investigation = investigation.model_copy(
                        update={"plan": plan, "updated_at": datetime.now(UTC)}
                    )
                    self.service.workspace.save(investigation, "plan_revised")
            elif action in {"b", "back"} and investigation.answers:
                investigation = investigation.model_copy(
                    update={
                        "answers": investigation.answers[:-1],
                        "brief": None,
                        "plan": None,
                        "status": InvestigationStatus.INTERVIEW,
                    }
                )
                self.service.workspace.save(investigation, "interview_reopened")
                return self._interview(investigation)
            elif action in {"q", "quit"}:
                return investigation

    def _review_collection(self, investigation: Investigation) -> Investigation:
        self._print_papers(investigation)
        while True:
            command = self.session.prompt("ragdoll> ").strip()
            if not command:
                continue
            name, _, argument = command.partition(" ")
            name = name.removeprefix("/").casefold()
            if name in {"quit", "q"}:
                return investigation
            if name in {"candidates", "staged"}:
                self._print_papers(investigation, staged_only=name == "staged")
            elif name == "inspect":
                self._inspect(investigation, argument)
            elif name in {"stage", "unstage"}:
                try:
                    paper_id = self._resolve_id(investigation, argument)
                    investigation = self.service.set_staged(
                        investigation, paper_id, name == "stage"
                    )
                    self.mascot.result(f"Paper {name}d.")
                except (KeyError, ValueError):
                    self.mascot.result("Paper not found; use its number or ID.", success=False)
            elif name == "export":
                self._export_all(investigation)
            elif name == "dossier":
                investigation = self._dossier(investigation, argument)
            elif name == "ask":
                question = argument.strip() or self.session.prompt("Question: ").strip()
                if question:
                    try:
                        with self.mascot.activity("planning", "Retrieving grounded evidence…"):
                            answer = self.service.ask(investigation, question)
                        chunk_ids = [item for claim in answer.claims for item in claim.chunk_ids]
                        self.console.print(
                            Markdown(
                                render_answer(answer, self.service.workspace.chunks(chunk_ids))
                            )
                        )
                    except (ValueError, ProviderError) as error:
                        self.mascot.result(str(error), success=False)
            elif name == "evidence":
                chunk = self.service.workspace.chunks([argument.strip()]).get(argument.strip())
                if chunk:
                    self.console.print(
                        Markdown(
                            f"## {chunk.paper_id} — {chunk.locator}\n\n"
                            f"**Evidence level:** {chunk.evidence_level}\n\n{chunk.text}"
                        )
                    )
                else:
                    self.mascot.result("Evidence citation not found.", success=False)
            elif name == "sources":
                self._print_sources(investigation)
            elif name == "purge-evidence":
                confirm = self.session.prompt(
                    "Delete cached documents and dossier? [y/N]: "
                ).strip()
                if confirm.casefold() in {"y", "yes"}:
                    try:
                        investigation = self.service.purge_evidence(investigation)
                        self.mascot.result("Local evidence cache and dossier deleted.")
                    except OSError as error:
                        self.mascot.result(f"Evidence purge failed: {error}", success=False)
            elif name == "plan" and investigation.plan:
                self._print_plan(
                    investigation.plan, investigation.brief.objective if investigation.brief else ""
                )
            elif name == "brief" and investigation.brief:
                self.console.print(
                    Markdown(f"## Research brief\n\n{investigation.brief.objective}")
                )
            elif name == "help":
                self.console.print(
                    "/candidates /staged /inspect N /stage N /unstage N /plan /brief "
                    "/dossier /ask QUESTION /evidence CHUNK /sources /export "
                    "/purge-evidence /quit"
                )
            else:
                self.console.print("[yellow]Unknown command. Use /help.[/yellow]")

    def _print_plan(self, plan: ResearchPlan, objective: str) -> None:
        axes = "\n".join(f"- {axis}" for axis in plan.investigation_axes)
        queries = "\n".join(
            f"- `{query.query}` — {query.rationale}" for query in plan.query_families
        )
        body = (
            f"# {plan.title}\n\n**Objective:** {objective}\n\n"
            f"## Axes\n{axes}\n\n## Queries\n{queries}"
        )
        self.console.print(Markdown(body))

    def _print_papers(self, investigation: Investigation, staged_only: bool = False) -> None:
        table = Table(title="Staged papers" if staged_only else "Paper candidates")
        table.add_column("#", justify="right")
        table.add_column("S")
        table.add_column("Paper")
        table.add_column("Year")
        table.add_column("Score", justify="right")
        for index, item in enumerate(investigation.papers, 1):
            if staged_only and not item.staged:
                continue
            table.add_row(
                str(index),
                "●" if item.staged else "",
                item.paper.title,
                str(item.paper.year or "—"),
                f"{item.score:.3f}",
            )
        self.console.print(table)

    def _inspect(self, investigation: Investigation, identifier: str) -> None:
        try:
            paper_id = self._resolve_id(investigation, identifier)
            item = next(item for item in investigation.papers if item.paper.id == paper_id)
        except (KeyError, ValueError, StopIteration):
            self.mascot.result("Paper not found.", success=False)
            return
        paper = item.paper
        self.console.print(
            Markdown(
                f"## {paper.title}\n\n**Authors:** {', '.join(paper.authors) or 'Unknown'}  \n"
                f"**Evidence:** {'abstract available' if paper.abstract else 'metadata only'}  \n"
                f"**Score:** {item.score:.3f}  \n"
                f"**Why:** {item.rationale}\n\n{paper.abstract or ''}"
            )
        )

    def _resolve_id(self, investigation: Investigation, identifier: str) -> str:
        identifier = identifier.strip()
        if identifier.isdigit():
            index = int(identifier) - 1
            if 0 <= index < len(investigation.papers):
                return investigation.papers[index].paper.id
        if any(item.paper.id == identifier for item in investigation.papers):
            return identifier
        raise KeyError(identifier)

    def _export_all(self, investigation: Investigation) -> None:
        directory = self.root / ".ragdoll" / "exports" / investigation.id
        for format, suffix in (("markdown", "md"), ("bibtex", "bib"), ("json", "json")):
            export_investigation(investigation, directory / f"reading-list.{suffix}", format)
        dossier = self.service.workspace.load_dossier(investigation.id)
        if dossier:
            chunk_ids = [
                item
                for section in dossier.sections
                for claim in section.claims
                for item in claim.chunk_ids
            ]
            chunks = self.service.workspace.chunks(chunk_ids)
            export_dossier(dossier, investigation, chunks, directory / "dossier.md", "markdown")
            export_dossier(dossier, investigation, chunks, directory / "dossier.json", "json")
        self.mascot.result(f"Exported Markdown, BibTeX, and JSON to {directory}")

    def _dossier(self, investigation: Investigation, argument: str = "") -> Investigation:
        existing = self.service.workspace.load_dossier(investigation.id)
        if existing:
            command, _, requested = argument.strip().partition(" ")
            if command.casefold() == "refresh":
                title = requested.strip() or "Open questions"
                if not self.service.workspace.remove_dossier_section(investigation.id, title):
                    canonical = next(
                        (
                            section_title
                            for section_title, _purpose in SECTION_SPECS
                            if section_title.casefold() == title.casefold()
                        ),
                        None,
                    )
                    existing_titles = {section.title.casefold() for section in existing.sections}
                    if canonical is None or canonical.casefold() in existing_titles:
                        self.mascot.result(f"Dossier section not found: {title}", success=False)
                        return investigation
                    title = canonical
                self.console.print(f"[dim]Regenerating dossier section: {title}[/dim]")
                return self._build_dossier(investigation)
            if investigation.dossier_status == DossierStatus.PARTIAL and len(existing.sections) < 7:
                resume = self.session.prompt("Dossier is incomplete; resume it? [y/N]: ").strip()
                if resume.casefold() in {"y", "yes"}:
                    return self._build_dossier(investigation)
            chunk_ids = [
                item
                for section in existing.sections
                for claim in section.claims
                for item in claim.chunk_ids
            ]
            self.console.print(
                Markdown(
                    render_dossier(
                        existing, investigation, self.service.workspace.chunks(chunk_ids)
                    )
                )
            )
            return investigation
        staged = [item for item in investigation.papers if item.staged]
        if not staged:
            self.mascot.result("Stage at least one paper before building a dossier.", success=False)
            return investigation
        limit = self.settings.dossier_paper_limit
        self.console.print(f"\n[bold]Dossier evidence preview[/bold] (first {limit} staged papers)")
        for item in staged[:limit]:
            level = (
                "open full text"
                if item.paper.fulltext_candidates
                else ("abstract fallback" if item.paper.abstract else "metadata only")
            )
            self.console.print(f"  • {item.paper.title} [dim]({level})[/dim]")
        investigation = self.service.mark_dossier_awaiting_approval(investigation)
        if self.settings.provider == "ollama":
            consent = "Download and parse open full text for local Ollama synthesis? [y/N]: "
        else:
            consent = (
                "Download and parse open full text, then send selected passages to "
                f"{self.settings.provider} for synthesis? [y/N]: "
            )
        confirmation = self.session.prompt(consent)
        if confirmation.strip().casefold() not in {"y", "yes"}:
            self.console.print(
                "[dim]Dossier acquisition cancelled; no documents were downloaded.[/dim]"
            )
            return investigation
        return self._build_dossier(investigation)

    def _build_dossier(self, investigation: Investigation) -> Investigation:
        try:
            with self.mascot.activity("staging", "Acquiring, indexing, and synthesizing evidence…"):
                investigation, dossier, warnings = self.service.build_dossier(investigation)
            for warning in warnings:
                self.console.print(f"[yellow]Evidence fallback: {warning}[/yellow]")
            chunk_ids = [
                item
                for section in dossier.sections
                for claim in section.claims
                for item in claim.chunk_ids
            ]
            self.console.print(
                Markdown(
                    render_dossier(dossier, investigation, self.service.workspace.chunks(chunk_ids))
                )
            )
            return investigation
        except (ValueError, ProviderError) as error:
            self.mascot.result(f"Dossier failed: {error}", success=False)
            return self.service.workspace.load(investigation.id)

    def _print_sources(self, investigation: Investigation) -> None:
        documents = self.service.workspace.list_documents(investigation.id)
        table = Table("Paper ID", "Evidence", "Status", "Pages", "Source")
        for document in documents:
            table.add_row(
                document.paper_id,
                document.evidence_level,
                document.status,
                str(document.page_count or "—"),
                document.source,
            )
        self.console.print(table)
