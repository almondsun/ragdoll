from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from ragdoll.config import Settings
from ragdoll.domain import DossierStatus, RelevanceBatch, RelevanceJudgment
from ragdoll.providers import OllamaProvider, OpenAIProvider, ProviderError, make_provider
from ragdoll.service import ResearchService
from ragdoll.sources import ScholarlySource


class StaticSource(ScholarlySource):
    name = "static"

    def __init__(self, papers) -> None:
        self.papers = papers

    def search(self, query: str, limit: int = 25):
        return [
            paper.model_copy(update={"queries": {query}, "source_ranks": [index]})
            for index, paper in enumerate(self.papers[:limit], 1)
        ]


class NoopCrossref:
    def enrich(self, paper):
        return paper


def test_ollama_structured_and_retry(brief) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = request.read().decode()
        assert '"think":false' in payload
        assert '"num_ctx":8192' in payload
        assert '"num_predict":2048' in payload
        if calls == 1:
            return httpx.Response(200, json={"message": {"content": "invalid"}})
        return httpx.Response(200, json={"message": {"content": brief.model_dump_json()}})

    provider = OllamaProvider(
        Settings(provider="ollama"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert (
        provider.structured(instructions="scope", prompt="topic", response_model=type(brief))
        == brief
    )
    assert calls == 2


def test_ollama_failure_and_unknown_provider(brief) -> None:
    provider = OllamaProvider(
        Settings(provider="ollama"),
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )
    with pytest.raises(ProviderError):
        provider.structured(instructions="", prompt="", response_model=type(brief))
    with pytest.raises(ProviderError, match="unsupported"):
        make_provider(Settings(provider="other"))


def test_default_ollama_client_ignores_environment_proxies(monkeypatch) -> None:
    options = {}

    class Client:
        def __init__(self, **kwargs) -> None:
            options.update(kwargs)

    monkeypatch.setattr("ragdoll.providers.httpx.Client", Client)
    OllamaProvider(Settings(provider="ollama"))
    assert options["trust_env"] is False


def test_openai_structured_success_and_failures(brief) -> None:
    class Response:
        def __init__(self, parsed) -> None:
            self.output_parsed = parsed

    class Responses:
        def __init__(self, result=None, error: Exception | None = None) -> None:
            self.result = result
            self.error = error

        def parse(self, **kwargs):
            assert kwargs["text_format"] is type(brief)
            if self.error:
                raise self.error
            return Response(self.result)

    class Client:
        def __init__(self, responses) -> None:
            self.responses = responses

    success = OpenAIProvider(Settings(), cast(Any, Client(Responses(brief))))
    assert success.structured(instructions="", prompt="", response_model=type(brief)) == brief
    empty = OpenAIProvider(Settings(), cast(Any, Client(Responses())))
    with pytest.raises(ProviderError, match="no structured"):
        empty.structured(instructions="", prompt="", response_model=type(brief))
    failure = OpenAIProvider(Settings(), cast(Any, Client(Responses(error=RuntimeError("bad")))))
    with pytest.raises(ProviderError, match="request failed"):
        failure.structured(instructions="", prompt="", response_model=type(brief))


def test_service_executes_and_persists(tmp_path: Path, investigation, papers, monkeypatch) -> None:
    judgment = RelevanceBatch(
        judgments=[
            RelevanceJudgment(
                paper_id=paper.id,
                topical_relevance=4,
                criteria_fit=4,
                axis_coverage=["architecture", "reproducibility"],
                evidence_availability=2,
                confidence=1,
                rationale="Strong match",
            )
            for paper in papers
        ]
    )
    from ragdoll.providers import FakeProvider

    provider = FakeProvider([judgment])
    source = StaticSource(papers)
    service = ResearchService(
        tmp_path,
        Settings(),
        provider,
        openalex=source,
        arxiv=StaticSource([]),
        crossref=NoopCrossref(),
    )
    approved = investigation.model_copy(
        update={"papers": [], "dossier_status": DossierStatus.READY}
    )
    service.workspace.save(approved)
    service.approve_plan(approved)
    result, warnings = service.execute(approved)
    assert not warnings
    assert len(result.papers) == 2
    assert result.status == "review"
    assert result.dossier_status == DossierStatus.NOT_STARTED
    assert service.workspace.latest() == result
    updated = service.set_staged(result, result.papers[1].paper.id, True)
    assert updated.papers[1].staged
    with pytest.raises(KeyError):
        service.set_staged(result, "missing", True)


def test_service_requires_approved_plan(tmp_path: Path, investigation) -> None:
    from ragdoll.providers import FakeProvider

    service = ResearchService(tmp_path, Settings(), FakeProvider([]))
    with pytest.raises(ValueError, match="approved"):
        service.execute(investigation.model_copy(update={"brief": None, "plan": None}))
    service.workspace.save(investigation)
    with pytest.raises(ValueError, match="explicitly approved"):
        service.execute(investigation)


def test_plan_revision_invalidates_approval(tmp_path: Path, investigation) -> None:
    from ragdoll.providers import FakeProvider

    service = ResearchService(tmp_path, Settings(), FakeProvider([]))
    service.workspace.save(investigation)
    service.approve_plan(investigation)
    revised = investigation.model_copy(
        update={"plan": investigation.plan.model_copy(update={"title": "Revised"})}
    )
    with pytest.raises(ValueError, match="explicitly approved"):
        service.execute(revised)


def test_staging_invalidates_dossier_and_requires_new_consent(
    tmp_path: Path, investigation
) -> None:
    from ragdoll.domain import ResearchDossier
    from ragdoll.providers import FakeProvider

    service = ResearchService(tmp_path, Settings(), FakeProvider([]))
    service.workspace.save(investigation)
    service.approve_evidence(investigation)
    service.workspace.save_dossier(
        investigation.id,
        ResearchDossier(
            title="Old",
            evidence_summary="old",
            sections=[{"title": "Summary", "claims": []}],
        ),
    )
    updated = service.set_staged(investigation, investigation.papers[1].paper.id, True)
    assert service.workspace.load_dossier(investigation.id) is None
    with pytest.raises(ValueError, match="explicitly approved"):
        service.build_dossier(updated)


def test_evidence_consent_is_bound_to_acquisition_limit(tmp_path: Path, investigation) -> None:
    from ragdoll.providers import FakeProvider

    first = ResearchService(tmp_path, Settings(dossier_paper_limit=1), FakeProvider([]))
    first.workspace.save(investigation)
    first.approve_evidence(investigation)
    changed = ResearchService(tmp_path, Settings(dossier_paper_limit=2), FakeProvider([]))
    with pytest.raises(ValueError, match="explicitly approved"):
        changed.build_dossier(investigation)
