"""Deterministic, offline sample data for the judge-facing product demo."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from .contracts import evidence_fingerprint, inference_fingerprint, staged_fingerprint
from .domain import (
    DocumentStatus,
    DossierSection,
    DossierStatus,
    EvidenceChunk,
    EvidenceDocument,
    EvidenceLevel,
    GroundedClaim,
    Investigation,
    InvestigationStatus,
    Paper,
    QueryFamily,
    RankedPaper,
    ResearchBrief,
    ResearchDossier,
    ResearchPlan,
)
from .service import ResearchService

DEMO_INVESTIGATION_ID = "build-week-demo"
DEMO_TIMESTAMP = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _section(title: str, text: str, chunk_ids: list[str]) -> DossierSection:
    return DossierSection(title=title, claims=[GroundedClaim(text=text, chunk_ids=chunk_ids)])


def seed_demo(service: ResearchService) -> Investigation:
    """Create a coherent sample workspace without network or model calls."""
    brief = ResearchBrief(
        original_prompt="How can research assistants preserve human control and source provenance?",
        objective="Compare evidence-centered designs for trustworthy scholarly research agents",
        audience="researchers and research-software engineers",
        scope=["human approval", "source provenance", "passage-level citations"],
        exclusions=["systems that expose only a generated answer"],
        date_from=date(2022, 1, 1),
        date_to=date(2026, 7, 18),
        preferred_evidence=["peer-reviewed papers", "technical system reports"],
        reproducibility_requirements=["inspectable retrieval and evidence boundaries"],
        desired_paper_count=3,
    )
    plan = ResearchPlan(
        title="Auditable scholarly research agents",
        research_questions=[
            "Where should human approval constrain an automated literature workflow?",
            "What provenance is needed to audit a generated research claim?",
        ],
        investigation_axes=["human control", "retrieval provenance", "citation grounding"],
        inclusion_criteria=["documents a concrete scholarly workflow"],
        exclusion_criteria=["answer-only demonstrations without inspectable evidence"],
        query_families=[
            QueryFamily(
                axis="human control",
                query="human in the loop scholarly research agent approval",
                rationale="Find explicit decision boundaries in research workflows.",
            ),
            QueryFamily(
                axis="retrieval provenance",
                query="literature search provenance reproducible retrieval",
                rationale="Find systems that preserve queries and source identifiers.",
            ),
            QueryFamily(
                axis="citation grounding",
                query="passage grounded citations research synthesis",
                rationale="Find claim-to-evidence validation approaches.",
            ),
        ],
        ranking_priorities=["workflow specificity", "auditability", "evidence access"],
    )
    paper_data = (
        (
            "demo:control",
            "Approval Boundaries in Assisted Literature Review",
            "A field study of editable plans, explicit search approval, and researcher curation.",
            "Human approval is most useful before retrieval and before evidence acquisition.",
        ),
        (
            "demo:provenance",
            "Reproducible Provenance for Scholarly Discovery",
            (
                "A system report on retaining exact queries, source identifiers, timestamps, "
                "and ranks."
            ),
            (
                "An audit record must retain the query, source identifier, retrieval time, "
                "and ranking context."
            ),
        ),
        (
            "demo:citations",
            "From Citation Markers to Inspectable Evidence",
            "An evaluation of claim-level citations linked to bounded source passages.",
            (
                "A citation becomes inspectable when it resolves to the exact passage supplied "
                "during synthesis."
            ),
        ),
    )
    ranked: list[RankedPaper] = []
    for index, (paper_id, title, abstract, _) in enumerate(paper_data):
        paper = Paper(
            id=paper_id,
            title=title,
            authors=["RAGdoll Demo Authors"],
            abstract=abstract,
            year=2026 - index,
            url=f"https://example.invalid/{paper_id.removeprefix('demo:')}",
            sources={"demo"},
            queries={plan.query_families[index].query},
            source_ranks=[index + 1],
            retrieved_at=DEMO_TIMESTAMP,
        )
        ranked.append(
            RankedPaper(
                paper=paper,
                score=0.92 - index * 0.06,
                rrf_score=0.03 - index * 0.004,
                relevance_score=0.95 - index * 0.05,
                criteria_score=0.90 - index * 0.04,
                axis_coverage=[plan.investigation_axes[index]],
                rationale="Directly addresses an approved investigation axis.",
                staged=True,
            )
        )
    investigation = Investigation(
        id=DEMO_INVESTIGATION_ID,
        created_at=DEMO_TIMESTAMP,
        updated_at=DEMO_TIMESTAMP,
        status=InvestigationStatus.REVIEW,
        original_prompt=brief.original_prompt,
        brief=brief,
        plan=plan,
        papers=ranked,
        dossier_status=DossierStatus.READY,
    )
    service.workspace.save(investigation, "offline_demo_seeded")

    acquisition = inference_fingerprint(
        investigation, service.evidence_approval_details(investigation)
    )
    chunks: list[EvidenceChunk] = []
    for index, (paper_id, _, _, passage) in enumerate(paper_data, 1):
        document = EvidenceDocument(
            id=f"demo-document-{index}",
            investigation_id=investigation.id,
            paper_id=paper_id,
            source="bundled synthetic sample",
            evidence_level=EvidenceLevel.FULL_TEXT,
            status=DocumentStatus.AVAILABLE,
            sha256=_digest(passage),
            media_type="text/plain",
            byte_count=len(passage.encode()),
            page_count=index + 2,
            acquired_at=DEMO_TIMESTAMP,
            staged_fingerprint=acquisition,
        )
        chunk = EvidenceChunk(
            id=f"demo-chunk-{index}",
            investigation_id=investigation.id,
            paper_id=paper_id,
            document_id=document.id,
            locator=f"page {index + 1}",
            evidence_level=EvidenceLevel.FULL_TEXT,
            text=passage,
            sha256=_digest(passage),
        )
        service.workspace.save_document(document, [chunk])
        chunks.append(chunk)

    documents = service.workspace.list_documents(investigation.id)
    acquired_ids = set(service.acquisition_paper_ids(investigation))
    dossier = ResearchDossier(
        title="Auditable scholarly research agents: evidence-grounded dossier",
        generated_at=DEMO_TIMESTAMP,
        evidence_summary=(
            "Offline synthetic demonstration: three staged documents and three inspectable "
            "passages."
        ),
        sections=[
            _section(
                "Executive summary",
                "Trustworthy research agents expose decisions and evidence.",
                [chunks[0].id, chunks[1].id],
            ),
            _section(
                "Landscape",
                "The sample workflow separates planning, retrieval, and synthesis.",
                [chunks[0].id],
            ),
            _section(
                "Technical approaches",
                "Reproducibility depends on retaining retrieval context.",
                [chunks[1].id],
            ),
            _section(
                "Evidence quality",
                "Claims remain inspectable when citations resolve to supplied passages.",
                [chunks[2].id],
            ),
            _section(
                "Agreements and disagreements",
                "Approval and provenance address different failure modes.",
                [chunks[0].id, chunks[1].id],
            ),
            _section(
                "Limitations",
                "Citation resolution alone does not prove entailment.",
                [chunks[2].id],
            ),
            _section(
                "Open questions",
                "Evaluation must test both retrieval quality and claim support.",
                [chunks[1].id, chunks[2].id],
            ),
        ],
        staged_fingerprint=staged_fingerprint(investigation),
        evidence_fingerprint=evidence_fingerprint(
            investigation, documents, acquired_ids, acquisition
        ),
        acquisition_fingerprint=acquisition,
        acquired_paper_ids=sorted(acquired_ids),
    )
    service.workspace.save_dossier(investigation.id, dossier)
    return investigation
