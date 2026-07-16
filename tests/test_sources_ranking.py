from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from ragdoll.domain import (
    FullTextCandidate,
    Paper,
    RankedPaper,
    RelevanceBatch,
    RelevanceJudgment,
    RetrievalHit,
)
from ragdoll.providers import FakeProvider
from ragdoll.ranking import deduplicate, reciprocal_rank, rerank, stage_diverse
from ragdoll.sources import (
    ArxivSource,
    CrossrefSource,
    OpenAlexSource,
    SourceError,
    normalize_title,
    search_all,
)


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openalex_normalizes_abstract_and_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search"] == "video"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Video Model",
                        "authorships": [{"author": {"display_name": "A. Author"}}],
                        "abstract_inverted_index": {"Video": [0], "works": [1]},
                        "publication_year": 2024,
                        "publication_date": "2024-01-02",
                        "doi": "https://doi.org/10.1/ABC",
                        "cited_by_count": 4,
                        "open_access": {"is_oa": True},
                        "primary_location": {
                            "landing_page_url": "https://example.test/paper",
                            "source": {"display_name": "Venue"},
                        },
                    }
                ]
            },
        )

    paper = OpenAlexSource(client(handler)).search("video")[0]
    assert paper.abstract == "Video works"
    assert paper.doi == "10.1/abc"
    assert paper.venue == "Venue"
    assert paper.retrieval_hits[0].model_dump(exclude={"retrieved_at"}) == {
        "source": "openalex",
        "source_id": "https://openalex.org/W1",
        "query": "video",
        "rank": 1,
    }


def test_arxiv_parses_atom() -> None:
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>https://arxiv.org/abs/2401.00001v1</id><published>2024-01-01T00:00:00Z</published>
    <title>  A Video Paper </title><summary>An abstract.</summary>
    <author><name>Ada Author</name></author></entry></feed>"""
    source = ArxivSource(client(lambda request: httpx.Response(200, content=xml)))
    paper = source.search("video")[0]
    assert paper.arxiv_id == "2401.00001v1"
    assert paper.title == "A Video Paper"


def test_source_failures_are_reported() -> None:
    source = OpenAlexSource(client(lambda request: httpx.Response(500)))
    with pytest.raises(SourceError):
        source.search("video")
    papers, warnings = search_all([source], ["video"])
    assert papers == []
    assert "OpenAlex" in warnings[0]


def test_dates_are_sent_to_provider_and_strictly_postfiltered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter"] == (
            "from_publication_date:2024-01-01,to_publication_date:2024-12-31"
        )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "unknown", "display_name": "Unknown", "primary_location": {}},
                    {
                        "id": "in-range",
                        "display_name": "In range",
                        "publication_date": "2024-03-01",
                        "primary_location": {},
                    },
                    {
                        "id": "outside",
                        "display_name": "Outside",
                        "publication_date": "2023-12-31",
                        "primary_location": {},
                    },
                ]
            },
        )

    papers, warnings = search_all(
        [OpenAlexSource(client(handler))],
        ["video"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 12, 31),
    )
    assert [paper.id for paper in papers] == ["in-range"]
    assert len(warnings) == 2


def test_crossref_enriches_without_making_failure_fatal(papers: list[Paper]) -> None:
    paper = papers[0].model_copy(update={"venue": None})
    success = client(
        lambda request: httpx.Response(
            200, json={"message": {"container-title": ["Journal"], "URL": "https://doi.org/x"}}
        )
    )
    enriched = CrossrefSource(success).enrich(paper)
    assert enriched.venue == "Journal"
    assert "crossref" in enriched.sources
    failed = CrossrefSource(client(lambda request: httpx.Response(500))).enrich(paper)
    assert failed == paper


def test_deduplication_merges_provenance(papers: list[Paper]) -> None:
    duplicate = papers[0].model_copy(
        update={
            "id": "other",
            "sources": {"arxiv"},
            "queries": {"other"},
            "source_ranks": [3],
            "fulltext_candidates": [
                FullTextCandidate(url="https://arxiv.org/pdf/1234", source="arxiv")
            ],
        }
    )
    result = deduplicate([papers[0], duplicate])
    assert len(result) == 1
    assert result[0].sources == {"openalex", "arxiv"}
    assert result[0].fulltext_candidates == duplicate.fulltext_candidates
    assert reciprocal_rank(result[0]) > reciprocal_rank(papers[0])
    assert normalize_title("A: Paper!") == "a paper"


def test_deduplication_links_preprint_and_published_aliases() -> None:
    retrieved = datetime.now(UTC)
    preprint = Paper(
        id="arxiv:1234.5678v2",
        title="A Shared Result",
        authors=["Ada Author"],
        arxiv_id="1234.5678v2",
        retrieval_hits=[
            RetrievalHit(
                source="arxiv",
                source_id="1234.5678v2",
                query="shared result",
                rank=2,
                retrieved_at=retrieved,
            )
        ],
        provenance_complete=True,
    )
    published = Paper(
        id="openalex:1",
        title="A Shared Result",
        authors=["Ada Author"],
        doi="10.1/shared",
        retrieval_hits=[
            RetrievalHit(
                source="openalex",
                source_id="openalex:1",
                query="shared paper",
                rank=1,
                retrieved_at=retrieved,
            )
        ],
        provenance_complete=True,
    )
    merged = deduplicate([preprint, published])
    assert len(merged) == 1
    assert merged[0].doi == "10.1/shared"
    assert {hit.source for hit in merged[0].retrieval_hits} == {"arxiv", "openalex"}


def test_diverse_staging_never_exceeds_requested_count(brief, plan, papers: list[Paper]) -> None:
    ranked = [
        RankedPaper(
            paper=paper.model_copy(update={"id": f"p-{index}"}),
            score=0.9,
            rrf_score=0.1,
            relevance_score=1,
            criteria_score=1,
            axis_coverage=[f"axis-{index}"],
            rationale="Relevant",
        )
        for index, paper in enumerate(papers * 2)
    ]
    staged = stage_diverse(ranked, [f"axis-{index}" for index in range(4)], 2)
    assert sum(item.staged for item in staged) == 2


def test_source_metadata_removes_terminal_controls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W2",
                        "display_name": "Safe\u001b[31m title",
                        "authorships": [],
                        "primary_location": {},
                    }
                ]
            },
        )

    paper = OpenAlexSource(client(handler)).search("safe")[0]
    assert "\u001b" not in paper.title


def test_rerank_and_diverse_staging(brief, plan, papers: list[Paper]) -> None:
    judgments = RelevanceBatch(
        judgments=[
            RelevanceJudgment(
                paper_id=papers[0].id,
                topical_relevance=4,
                criteria_fit=4,
                axis_coverage=["architecture"],
                evidence_availability=2,
                confidence=0.9,
                rationale="Architecture match",
            ),
            RelevanceJudgment(
                paper_id=papers[1].id,
                topical_relevance=3,
                criteria_fit=4,
                axis_coverage=["reproducibility"],
                evidence_availability=2,
                confidence=0.8,
                rationale="Open implementation",
            ),
        ]
    )
    ranked = rerank(papers, brief, plan, FakeProvider([judgments]))
    staged = stage_diverse(ranked, plan.investigation_axes, 2)
    assert ranked[0].paper.id == papers[0].id
    assert all(item.staged for item in staged)
    assert {axis for item in staged for axis in item.axis_coverage} == {
        "architecture",
        "reproducibility",
    }


def test_rerank_batches_local_model_work(brief, plan, papers: list[Paper]) -> None:
    candidates = [
        papers[0].model_copy(update={"id": f"paper-{index}", "source_ranks": [index + 1]})
        for index in range(7)
    ]

    def judgments(values: list[Paper]) -> RelevanceBatch:
        return RelevanceBatch(
            judgments=[
                RelevanceJudgment(
                    paper_id=paper.id,
                    topical_relevance=3,
                    criteria_fit=3,
                    evidence_availability=2,
                    confidence=0.8,
                    rationale="Relevant to the approved scope.",
                )
                for paper in values
            ]
        )

    provider = FakeProvider(
        [
            judgments(candidates[:3]),
            judgments(candidates[3:6]),
            judgments(candidates[6:]),
        ]
    )
    assert len(rerank(candidates, brief, plan, provider)) == 7
    assert not provider.responses
