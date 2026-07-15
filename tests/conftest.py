from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ragdoll.domain import (
    Investigation,
    InvestigationStatus,
    Paper,
    QueryFamily,
    RankedPaper,
    ResearchBrief,
    ResearchPlan,
)


@pytest.fixture
def brief() -> ResearchBrief:
    return ResearchBrief(
        original_prompt="video generation models",
        objective="Understand open video generation architectures",
        audience="technical researcher",
        scope=["text-to-video", "open implementations"],
        exclusions=["closed demos without technical detail"],
        preferred_evidence=["primary papers"],
        reproducibility_requirements=["code or weights preferred"],
        desired_paper_count=3,
    )


@pytest.fixture
def plan() -> ResearchPlan:
    return ResearchPlan(
        title="Open video generation models",
        research_questions=["Which architectures dominate?"],
        investigation_axes=["architecture", "reproducibility"],
        inclusion_criteria=["technical paper"],
        exclusion_criteria=["marketing pages"],
        query_families=[
            QueryFamily(
                axis="architecture",
                query="video diffusion transformer",
                rationale="Find the central architecture family",
            )
        ],
        ranking_priorities=["technical relevance"],
    )


@pytest.fixture
def papers() -> list[Paper]:
    return [
        Paper(
            id="https://openalex.org/W1",
            title="Video Diffusion Transformers",
            authors=["Ada Researcher"],
            abstract="A diffusion transformer for temporally coherent video generation.",
            year=2024,
            doi="10.1/video",
            url="https://doi.org/10.1/video",
            sources={"openalex"},
            queries={"video diffusion"},
            source_ranks=[1],
        ),
        Paper(
            id="arxiv:2401.00001v1",
            arxiv_id="2401.00001v1",
            title="Open Video Generation",
            authors=["Lin Scholar"],
            abstract="An open implementation and evaluation.",
            year=2024,
            url="https://arxiv.org/abs/2401.00001",
            sources={"arxiv"},
            queries={"open video"},
            source_ranks=[2],
        ),
    ]


@pytest.fixture
def investigation(brief: ResearchBrief, plan: ResearchPlan, papers: list[Paper]) -> Investigation:
    now = datetime.now(UTC)
    ranked = [
        RankedPaper(
            paper=paper,
            score=0.8 - index * 0.1,
            rrf_score=0.02,
            relevance_score=0.75,
            criteria_score=0.75,
            axis_coverage=["architecture"],
            rationale="Directly addresses the approved scope.",
            staged=index == 0,
        )
        for index, paper in enumerate(papers)
    ]
    return Investigation(
        id="abc123",
        created_at=now,
        updated_at=now,
        status=InvestigationStatus.REVIEW,
        original_prompt=brief.original_prompt,
        brief=brief,
        plan=plan,
        papers=ranked,
    )
