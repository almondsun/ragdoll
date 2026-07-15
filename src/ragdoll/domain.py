"""Validated domain contracts shared across RAGdoll boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class ClarificationOption(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=180)


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


class QueryFamily(BaseModel):
    axis: str = Field(min_length=1)
    query: str = Field(min_length=2, max_length=300)
    rationale: str = Field(min_length=1, max_length=300)


class ResearchPlan(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    research_questions: list[str] = Field(min_length=1, max_length=8)
    investigation_axes: list[str] = Field(min_length=1, max_length=8)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    query_families: list[QueryFamily] = Field(min_length=1, max_length=12)
    sources: list[str] = Field(default_factory=lambda: ["openalex", "arxiv"])
    ranking_priorities: list[str] = Field(default_factory=list)


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
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RelevanceJudgment(BaseModel):
    paper_id: str
    topical_relevance: int = Field(ge=0, le=4)
    criteria_fit: int = Field(ge=0, le=4)
    axis_coverage: list[str] = Field(default_factory=list)
    evidence_availability: int = Field(ge=0, le=2)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=400)


class RelevanceBatch(BaseModel):
    judgments: list[RelevanceJudgment]


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


PaperId = Annotated[str, Field(min_length=1)]
