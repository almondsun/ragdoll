"""Adaptive clarification and research-plan construction."""

from __future__ import annotations

import json

from pydantic import BaseModel, model_validator

from .domain import (
    ClarificationAnswer,
    ClarificationQuestion,
    ResearchBrief,
    ResearchPlan,
)
from .providers import ModelProvider


class InterviewTurn(BaseModel):
    complete: bool
    question: ClarificationQuestion | None = None

    @model_validator(mode="after")
    def valid_state(self) -> InterviewTurn:
        if self.complete == (self.question is not None):
            raise ValueError("complete turns omit a question; incomplete turns require one")
        return self


CLARIFIER_INSTRUCTIONS = """
You scope scholarly literature searches. Ask only one pivotal question whose answer would
materially change queries, filters, ranking, or output. Supply exactly three distinct, concise
proposed answers;
the terminal adds its own custom-answer option. Do not repeat answered dimensions. Mark complete
when the request is sufficiently scoped. Never perform the research.
""".strip()

BRIEF_INSTRUCTIONS = """
Compile the user's request and clarification answers into a faithful scholarly research brief.
Do not invent constraints. Use a default desired collection of 12 papers. Preserve open-ended
dimensions instead of silently narrowing them.
""".strip()

PLAN_INSTRUCTIONS = """
Create a concise, executable scholarly discovery plan. Generate diverse query families mapped to
investigation axes. Use OpenAlex and arXiv. Prefer primary scholarship, expose inclusion and
exclusion criteria, and do not claim that any search is exhaustive.
""".strip()


class Planner:
    def __init__(self, provider: ModelProvider, max_questions: int = 6) -> None:
        self.provider = provider
        self.max_questions = max_questions

    def next_question(
        self, original_prompt: str, answers: list[ClarificationAnswer]
    ) -> ClarificationQuestion | None:
        if len(answers) >= self.max_questions:
            return None
        prompt = json.dumps(
            {
                "original_request": original_prompt,
                "answers": [answer.model_dump() for answer in answers],
                "remaining_question_budget": self.max_questions - len(answers),
            },
            ensure_ascii=False,
        )
        turn = self.provider.structured(
            instructions=CLARIFIER_INSTRUCTIONS,
            prompt=prompt,
            response_model=InterviewTurn,
        )
        if turn.complete:
            return None
        assert turn.question is not None
        previous_ids = {answer.question_id for answer in answers}
        if turn.question.id in previous_ids:
            raise ValueError(f"provider repeated clarification question {turn.question.id!r}")
        return turn.question

    def build_brief(
        self, original_prompt: str, answers: list[ClarificationAnswer]
    ) -> ResearchBrief:
        return self.provider.structured(
            instructions=BRIEF_INSTRUCTIONS,
            prompt=json.dumps(
                {
                    "original_request": original_prompt,
                    "answers": [answer.model_dump() for answer in answers],
                },
                ensure_ascii=False,
            ),
            response_model=ResearchBrief,
            quality=True,
        )

    def build_plan(self, brief: ResearchBrief) -> ResearchPlan:
        return self.provider.structured(
            instructions=PLAN_INSTRUCTIONS,
            prompt=brief.model_dump_json(),
            response_model=ResearchPlan,
            quality=True,
        )

    def revise_plan(self, brief: ResearchBrief, plan: ResearchPlan, request: str) -> ResearchPlan:
        return self.provider.structured(
            instructions=(
                PLAN_INSTRUCTIONS
                + "\nRevise the existing plan only as requested. Preserve unaffected user "
                "decisions."
            ),
            prompt=json.dumps(
                {
                    "brief": brief.model_dump(mode="json"),
                    "existing_plan": plan.model_dump(mode="json"),
                    "revision_request": request,
                },
                ensure_ascii=False,
            ),
            response_model=ResearchPlan,
            quality=True,
        )
