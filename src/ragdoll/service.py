"""Application orchestration for discovery, ranking, staging, and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .contracts import (
    evidence_fingerprint,
    inference_fingerprint,
    plan_fingerprint,
    staged_fingerprint,
)
from .domain import (
    ApprovalKind,
    ApprovalRecord,
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
        fingerprint = plan_fingerprint(investigation)
        if self.workspace.approval_for(investigation.id, ApprovalKind.PLAN, fingerprint) is None:
            raise ValueError("the current research plan has not been explicitly approved")
        brief = investigation.brief
        plan = investigation.plan
        searching = investigation.model_copy(
            update={
                "status": InvestigationStatus.SEARCHING,
                "dossier_status": DossierStatus.NOT_STARTED,
                "updated_at": _now(),
            }
        )
        self.workspace.save(searching, "search_started")
        queries = [family.query for family in plan.query_families]
        source_registry = {"openalex": self.openalex, "arxiv": self.arxiv}
        sources = [source_registry[name] for name in plan.sources]
        found, warnings = search_all(
            sources,
            queries,
            date_from=brief.date_from,
            date_to=brief.date_to,
        )
        unique = deduplicate(found)
        if "crossref" in plan.metadata_sources:
            enriched = [self.crossref.enrich(paper) for paper in unique[:50]] + unique[50:]
        else:
            enriched = unique
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
        self.workspace.invalidate_derived(investigation.id)
        return complete, warnings

    def approve_plan(self, investigation: Investigation) -> ApprovalRecord:
        approval = ApprovalRecord(
            investigation_id=investigation.id,
            kind=ApprovalKind.PLAN,
            fingerprint=plan_fingerprint(investigation),
            details={"scope": "discovery"},
        )
        self.workspace.approve(approval)
        return approval

    def inference_details(self) -> dict[str, str]:
        if self.settings.provider == "ollama":
            return {
                "provider": "ollama",
                "model": self.settings.ollama_model,
                "endpoint": self.settings.ollama_url,
                "transport": "local" if self.settings.ollama_is_local else "remote",
            }
        return {
            "provider": "openai",
            "model": self.settings.openai_model_quality,
            "endpoint": "https://api.openai.com",
            "transport": "remote",
        }

    def approve_evidence(self, investigation: Investigation) -> ApprovalRecord:
        details = self.evidence_approval_details(investigation)
        approval = ApprovalRecord(
            investigation_id=investigation.id,
            kind=ApprovalKind.EVIDENCE,
            fingerprint=inference_fingerprint(investigation, details),
            details=details,
        )
        self.workspace.approve(approval)
        return approval

    def evidence_approval_details(self, investigation: Investigation) -> dict[str, str]:
        details = self.inference_details()
        acquired = self.acquisition_paper_ids(investigation)
        return details | {
            "dossier_paper_limit": str(self.settings.dossier_paper_limit),
            "acquired_paper_ids": ",".join(acquired),
        }

    def acquisition_paper_ids(self, investigation: Investigation) -> list[str]:
        return [item.paper.id for item in investigation.papers if item.staged][
            : self.settings.dossier_paper_limit
        ]

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
        if staged_fingerprint(updated) != staged_fingerprint(investigation):
            self.workspace.invalidate_derived(investigation.id)
            updated = updated.model_copy(update={"dossier_status": DossierStatus.NOT_STARTED})
        self.workspace.save(updated, "paper_staged" if staged else "paper_unstaged")
        return updated

    def build_dossier(
        self, investigation: Investigation
    ) -> tuple[Investigation, ResearchDossier, list[str]]:
        if not any(item.staged for item in investigation.papers):
            raise ValueError("stage at least one paper before building a dossier")
        approval_fingerprint = inference_fingerprint(
            investigation, self.evidence_approval_details(investigation)
        )
        if (
            self.workspace.approval_for(
                investigation.id, ApprovalKind.EVIDENCE, approval_fingerprint
            )
            is None
        ):
            raise ValueError("evidence acquisition and inference have not been explicitly approved")
        acquiring = investigation.model_copy(
            update={"dossier_status": DossierStatus.ACQUIRING, "updated_at": _now()}
        )
        self.workspace.save(acquiring, "dossier_acquisition_started")
        acquired_ids = set(self.acquisition_paper_ids(investigation))
        _, warnings = self.evidence.acquire(acquiring, approval_fingerprint)
        indexing = acquiring.model_copy(
            update={"dossier_status": DossierStatus.INDEXING, "updated_at": _now()}
        )
        self.workspace.save(indexing, "dossier_evidence_indexed")
        synthesizing = indexing.model_copy(
            update={"dossier_status": DossierStatus.SYNTHESIZING, "updated_at": _now()}
        )
        self.workspace.save(synthesizing, "dossier_synthesis_started")
        try:
            dossier = self.synthesizer.generate(synthesizing, approval_fingerprint, acquired_ids)
        except Exception:
            partial = synthesizing.model_copy(
                update={"dossier_status": DossierStatus.PARTIAL, "updated_at": _now()}
            )
            self.workspace.save(partial, "dossier_synthesis_failed")
            raise
        documents = self.workspace.list_documents(investigation.id)
        dossier = dossier.model_copy(
            update={
                "staged_fingerprint": staged_fingerprint(investigation),
                "evidence_fingerprint": evidence_fingerprint(
                    investigation, documents, acquired_ids, approval_fingerprint
                ),
                "acquisition_fingerprint": approval_fingerprint,
                "acquired_paper_ids": sorted(acquired_ids),
            }
        )
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
        dossier = self.workspace.load_dossier(investigation.id)
        documents = self.workspace.list_documents(investigation.id)
        approval_fingerprint = inference_fingerprint(
            investigation, self.evidence_approval_details(investigation)
        )
        acquired_ids = set(self.acquisition_paper_ids(investigation))
        if (
            dossier is None
            or dossier.staged_fingerprint != staged_fingerprint(investigation)
            or dossier.evidence_fingerprint
            != evidence_fingerprint(investigation, documents, acquired_ids, approval_fingerprint)
        ):
            raise ValueError("the dossier is stale; rebuild it before asking evidence questions")
        return self.synthesizer.answer(investigation, question, approval_fingerprint, acquired_ids)

    def current_dossier(self, investigation: Investigation) -> ResearchDossier | None:
        dossier = self.workspace.load_dossier(investigation.id)
        if dossier is None:
            return None
        documents = self.workspace.list_documents(investigation.id)
        approval_fingerprint = inference_fingerprint(
            investigation, self.evidence_approval_details(investigation)
        )
        acquired_ids = set(self.acquisition_paper_ids(investigation))
        if dossier.staged_fingerprint != staged_fingerprint(
            investigation
        ) or dossier.evidence_fingerprint != evidence_fingerprint(
            investigation, documents, acquired_ids, approval_fingerprint
        ):
            return None
        return dossier

    def purge_evidence(self, investigation: Investigation) -> Investigation:
        self.workspace.purge_evidence(investigation.id)
        updated = investigation.model_copy(
            update={"dossier_status": DossierStatus.NOT_STARTED, "updated_at": _now()}
        )
        self.workspace.save(updated, "dossier_evidence_purged")
        return updated


def _now() -> datetime:
    return datetime.now(UTC)
