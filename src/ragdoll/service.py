"""Application orchestration for discovery, ranking, staging, and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .domain import (
    DossierStatus,
    GroundedAnswer,
    Investigation,
    InvestigationStatus,
    ResearchDossier,
)
from .evidence import EvidenceService
from .providers import ModelProvider
from .ranking import deduplicate, rerank, stage_diverse
from .sources import ArxivSource, CrossrefSource, OpenAlexSource, search_all
from .storage import Workspace
from .synthesis import Synthesizer


class ResearchService:
    def __init__(
        self,
        root: Path,
        settings: Settings,
        provider: ModelProvider,
        openalex: OpenAlexSource | None = None,
        arxiv: ArxivSource | None = None,
        crossref: CrossrefSource | None = None,
        evidence: EvidenceService | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.workspace = Workspace(root)
        self.openalex = openalex or OpenAlexSource(mailto=settings.openalex_mailto)
        self.arxiv = arxiv or ArxivSource()
        self.crossref = crossref or CrossrefSource(mailto=settings.openalex_mailto)
        self.evidence = evidence or EvidenceService(root, settings, self.workspace)
        self.synthesizer = Synthesizer(provider, self.workspace)

    def execute(self, investigation: Investigation) -> tuple[Investigation, list[str]]:
        if investigation.brief is None or investigation.plan is None:
            raise ValueError("an approved brief and plan are required before search")
        brief = investigation.brief
        plan = investigation.plan
        searching = investigation.model_copy(
            update={"status": InvestigationStatus.SEARCHING, "updated_at": _now()}
        )
        self.workspace.save(searching, "search_started")
        queries = [family.query for family in plan.query_families]
        found, warnings = search_all([self.openalex, self.arxiv], queries)
        unique = deduplicate(found)
        enriched = [self.crossref.enrich(paper) for paper in unique[:50]] + unique[50:]
        ranked = rerank(enriched, brief, plan, self.provider)
        staged = stage_diverse(
            ranked,
            plan.investigation_axes,
            brief.desired_paper_count,
        )
        complete = searching.model_copy(
            update={
                "papers": staged,
                "status": InvestigationStatus.REVIEW,
                "updated_at": _now(),
            }
        )
        self.workspace.save(complete, "search_completed")
        return complete, warnings

    def set_staged(
        self, investigation: Investigation, paper_id: str, staged: bool
    ) -> Investigation:
        if not any(item.paper.id == paper_id for item in investigation.papers):
            raise KeyError(paper_id)
        papers = [
            item.model_copy(update={"staged": staged}) if item.paper.id == paper_id else item
            for item in investigation.papers
        ]
        updated = investigation.model_copy(update={"papers": papers, "updated_at": _now()})
        self.workspace.save(updated, "paper_staged" if staged else "paper_unstaged")
        return updated

    def build_dossier(
        self, investigation: Investigation
    ) -> tuple[Investigation, ResearchDossier, list[str]]:
        if not any(item.staged for item in investigation.papers):
            raise ValueError("stage at least one paper before building a dossier")
        acquiring = investigation.model_copy(
            update={"dossier_status": DossierStatus.ACQUIRING, "updated_at": _now()}
        )
        self.workspace.save(acquiring, "dossier_acquisition_started")
        _, warnings = self.evidence.acquire(acquiring)
        indexing = acquiring.model_copy(
            update={"dossier_status": DossierStatus.INDEXING, "updated_at": _now()}
        )
        self.workspace.save(indexing, "dossier_evidence_indexed")
        synthesizing = indexing.model_copy(
            update={"dossier_status": DossierStatus.SYNTHESIZING, "updated_at": _now()}
        )
        self.workspace.save(synthesizing, "dossier_synthesis_started")
        try:
            dossier = self.synthesizer.generate(synthesizing)
        except Exception:
            partial = synthesizing.model_copy(
                update={"dossier_status": DossierStatus.PARTIAL, "updated_at": _now()}
            )
            self.workspace.save(partial, "dossier_synthesis_failed")
            raise
        self.workspace.save_dossier(investigation.id, dossier)
        status = DossierStatus.PARTIAL if warnings else DossierStatus.READY
        complete = synthesizing.model_copy(update={"dossier_status": status, "updated_at": _now()})
        self.workspace.save(complete, "dossier_completed")
        return complete, dossier, warnings

    def mark_dossier_awaiting_approval(self, investigation: Investigation) -> Investigation:
        updated = investigation.model_copy(
            update={"dossier_status": DossierStatus.AWAITING_APPROVAL, "updated_at": _now()}
        )
        self.workspace.save(updated, "dossier_approval_requested")
        return updated

    def ask(self, investigation: Investigation, question: str) -> GroundedAnswer:
        if not self.workspace.list_documents(investigation.id):
            raise ValueError("build a dossier before asking evidence questions")
        return self.synthesizer.answer(investigation, question)

    def purge_evidence(self, investigation: Investigation) -> Investigation:
        self.workspace.purge_evidence(investigation.id)
        updated = investigation.model_copy(
            update={"dossier_status": DossierStatus.NOT_STARTED, "updated_at": _now()}
        )
        self.workspace.save(updated, "dossier_evidence_purged")
        return updated


def _now() -> datetime:
    return datetime.now(UTC)
