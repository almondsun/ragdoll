"""Validated domain contracts shared across RAGdoll boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ClarificationOption(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=180)

    @field_validator("label")
    @classmethod
    def label_is_descriptive(cls, value: str) -> str:
        if not any(character.isalpha() for character in value):
            raise ValueError("clarification option labels must be descriptive")
        return value


class ClarificationQuestion(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    question: str = Field(min_length=8, max_length=240)
    options: tuple[ClarificationOption, ClarificationOption, ClarificationOption]

    @model_validator(mode="after")
    def options_are_distinct(self) -> ClarificationQuestion:
        labels = {option.label.casefold().strip() for option in self.options}
        if len(labels) != 3:
            raise ValueError("clarification option labels must be distinct")
        return self


class ClarificationAnswer(BaseModel):
    question_id: str
    question: str
    answer: str = Field(min_length=1)
    option_labels: list[str] = Field(default_factory=list, max_length=3)


class ResearchBrief(BaseModel):
    original_prompt: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    audience: str | None = None
    scope: list[str] = Field(min_length=1)
    exclusions: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    preferred_evidence: list[str] = Field(default_factory=list)
    reproducibility_requirements: list[str] = Field(default_factory=list)
    desired_paper_count: int = Field(default=12, ge=3, le=50)

    @model_validator(mode="after")
    def dates_are_ordered(self) -> ResearchBrief:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class QueryFamily(BaseModel):
    axis: str = Field(min_length=1)
    query: str = Field(min_length=2, max_length=300)
    rationale: str = Field(min_length=1, max_length=300)


DiscoverySource = Literal["openalex", "arxiv"]
MetadataSource = Literal["crossref"]


def _default_discovery_sources() -> list[DiscoverySource]:
    return ["openalex", "arxiv"]


def _default_metadata_sources() -> list[MetadataSource]:
    return ["crossref"]


class ResearchPlan(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    research_questions: list[str] = Field(min_length=1, max_length=8)
    investigation_axes: list[str] = Field(min_length=1, max_length=8)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    query_families: list[QueryFamily] = Field(min_length=1, max_length=12)
    sources: list[DiscoverySource] = Field(default_factory=_default_discovery_sources, min_length=1)
    metadata_sources: list[MetadataSource] = Field(default_factory=_default_metadata_sources)
    ranking_priorities: list[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def discovery_sources_are_supported(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.casefold().strip() for value in values))
        unsupported = sorted(set(normalized) - {"openalex", "arxiv"})
        if unsupported:
            raise ValueError(f"unsupported discovery sources: {', '.join(unsupported)}")
        return normalized

    @field_validator("metadata_sources", mode="before")
    @classmethod
    def metadata_sources_are_supported(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.casefold().strip() for value in values))
        unsupported = sorted(set(normalized) - {"crossref"})
        if unsupported:
            raise ValueError(f"unsupported metadata sources: {', '.join(unsupported)}")
        return normalized


class RetrievalHit(BaseModel):
    source: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    rank: int = Field(ge=1)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FullTextCandidate(BaseModel):
    url: str = Field(pattern=r"^https://")
    source: str = Field(min_length=1)
    license: str | None = None
    version: str | None = None


class Paper(BaseModel):
    id: str
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    cited_by_count: int = Field(default=0, ge=0)
    open_access: bool | None = None
    sources: set[str] = Field(default_factory=set)
    queries: set[str] = Field(default_factory=set)
    source_ranks: list[int] = Field(default_factory=list)
    retrieval_hits: list[RetrievalHit] = Field(default_factory=list)
    provenance_complete: bool = False
    fulltext_candidates: list[FullTextCandidate] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RelevanceJudgment(BaseModel):
    paper_id: str
    topical_relevance: int = Field(ge=0, le=4)
    criteria_fit: int = Field(ge=0, le=4)
    axis_coverage: list[str] = Field(default_factory=list)
    evidence_availability: int = Field(ge=0, le=2)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=160)


class RelevanceBatch(BaseModel):
    judgments: list[RelevanceJudgment]

    @model_validator(mode="after")
    def paper_ids_are_distinct(self) -> RelevanceBatch:
        identifiers = [judgment.paper_id for judgment in self.judgments]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("relevance judgments must have distinct paper IDs")
        return self


class RankedPaper(BaseModel):
    paper: Paper
    score: float = Field(ge=0, le=1)
    rrf_score: float = Field(ge=0)
    relevance_score: float = Field(ge=0, le=1)
    criteria_score: float = Field(ge=0, le=1)
    axis_coverage: list[str] = Field(default_factory=list)
    rationale: str
    staged: bool = False


class InvestigationStatus(StrEnum):
    INTERVIEW = "interview"
    PLAN_REVIEW = "plan_review"
    SEARCHING = "searching"
    REVIEW = "review"
    COMPLETE = "complete"


class ApprovalKind(StrEnum):
    PLAN = "plan"
    EVIDENCE = "evidence"


class ApprovalRecord(BaseModel):
    investigation_id: str
    kind: ApprovalKind
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, str] = Field(default_factory=dict)


class DossierStatus(StrEnum):
    NOT_STARTED = "not_started"
    AWAITING_APPROVAL = "awaiting_approval"
    ACQUIRING = "acquiring"
    INDEXING = "indexing"
    SYNTHESIZING = "synthesizing"
    READY = "ready"
    PARTIAL = "partial"


class Investigation(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    created_at: datetime
    updated_at: datetime
    status: InvestigationStatus
    original_prompt: str
    answers: list[ClarificationAnswer] = Field(default_factory=list)
    brief: ResearchBrief | None = None
    plan: ResearchPlan | None = None
    papers: list[RankedPaper] = Field(default_factory=list)
    dossier_status: DossierStatus = DossierStatus.NOT_STARTED


class EvidenceLevel(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"
    METADATA = "metadata"


class DocumentStatus(StrEnum):
    AVAILABLE = "available"
    FALLBACK = "fallback"
    FAILED = "failed"


class EvidenceDocument(BaseModel):
    id: str
    investigation_id: str
    paper_id: str
    source_url: str | None = None
    source: str
    license: str | None = None
    evidence_level: EvidenceLevel
    status: DocumentStatus
    sha256: str | None = None
    media_type: str | None = None
    byte_count: int | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    relative_path: str | None = None
    error: str | None = None
    staged_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class EvidenceChunk(BaseModel):
    id: str
    investigation_id: str
    paper_id: str
    document_id: str
    locator: str
    evidence_level: EvidenceLevel
    text: str = Field(min_length=1)
    sha256: str


class GroundedClaim(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    chunk_ids: list[str] = Field(min_length=1, max_length=6)


class DossierSection(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    claims: list[GroundedClaim] = Field(default_factory=list)


class ResearchDossier(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence_summary: str = Field(min_length=1)
    sections: list[DossierSection] = Field(min_length=1)
    staged_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    acquisition_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    acquired_paper_ids: list[str] = Field(default_factory=list)


class GroundedAnswer(BaseModel):
    question: str = Field(min_length=1)
    claims: list[GroundedClaim] = Field(default_factory=list)
    insufficient_evidence: bool = False
    explanation: str = Field(min_length=1, max_length=800)
    staged_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def insufficiency_is_explicit(self) -> GroundedAnswer:
        if self.insufficient_evidence and self.claims:
            raise ValueError("an insufficient-evidence answer cannot contain factual claims")
        if not self.insufficient_evidence and not self.claims:
            raise ValueError("a grounded answer requires at least one cited claim")
        return self


PaperId = Annotated[str, Field(min_length=1)]
