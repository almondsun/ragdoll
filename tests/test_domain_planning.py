from __future__ import annotations

import pytest
from pydantic import ValidationError

from ragdoll.domain import (
    ClarificationAnswer,
    ClarificationOption,
    ClarificationQuestion,
    ResearchBrief,
    ResearchPlan,
)
from ragdoll.planning import InterviewTurn, Planner
from ragdoll.providers import FakeProvider, ProviderError


def question() -> ClarificationQuestion:
    return ClarificationQuestion(
        id="research_goal",
        question="What should the investigation optimize for?",
        options=(
            ClarificationOption(label="Understanding", description="Build foundations"),
            ClarificationOption(label="Comparison", description="Compare current methods"),
            ClarificationOption(label="Direction", description="Find an open direction"),
        ),
    )


def test_question_requires_exactly_three_distinct_options() -> None:
    value = question()
    assert len(value.options) == 3
    with pytest.raises(ValidationError, match="distinct"):
        ClarificationQuestion(
            id="goal",
            question="Which goal matters most?",
            options=(value.options[0], value.options[0], value.options[2]),
        )


def test_investigation_ids_are_path_safe(investigation) -> None:
    with pytest.raises(ValidationError):
        investigation.model_copy(update={"id": "../../escape"}, deep=True).__class__.model_validate(
            {**investigation.model_dump(), "id": "../../escape"}
        )


def test_interview_turn_requires_consistent_state() -> None:
    with pytest.raises(ValidationError):
        InterviewTurn(complete=True, question=question())
    with pytest.raises(ValidationError):
        InterviewTurn(complete=False)


def test_planner_runs_adaptive_flow(brief: ResearchBrief, plan: ResearchPlan) -> None:
    provider = FakeProvider([InterviewTurn(complete=False, question=question()), brief, plan, plan])
    planner = Planner(provider)
    selected = planner.next_question("video", [])
    assert selected == question()
    answers = [
        ClarificationAnswer(
            question_id=selected.id,
            question=selected.question,
            answer="Comparison",
        )
    ]
    assert planner.build_brief("video", answers) == brief
    assert planner.build_plan(brief) == plan
    assert planner.revise_plan(brief, plan, "Prefer open work") == plan


def test_planner_stops_and_rejects_repeated_questions() -> None:
    planner = Planner(FakeProvider([]), max_questions=1)
    answer = ClarificationAnswer(question_id="goal", question="Goal?", answer="Learn")
    assert planner.next_question("topic", [answer]) is None

    repeated = ClarificationQuestion(
        id="goal",
        question="What is the research goal?",
        options=question().options,
    )
    planner = Planner(FakeProvider([InterviewTurn(complete=False, question=repeated)]))
    with pytest.raises(ValueError, match="repeated"):
        planner.next_question("topic", [answer])


def test_fake_provider_exhaustion() -> None:
    provider = FakeProvider([])
    with pytest.raises(ProviderError, match="empty"):
        provider.structured(instructions="", prompt="", response_model=ResearchPlan)
