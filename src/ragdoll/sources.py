"""Read-only scholarly discovery and metadata normalization."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, ClassVar
from urllib.parse import quote
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as ET

from .domain import FullTextCandidate, Paper

DOI_PREFIX = "https://doi.org/"


class SourceError(RuntimeError):
    pass


class ScholarlySource(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, limit: int = 25) -> list[Paper]: ...


class OpenAlexSource(ScholarlySource):
    name = "openalex"

    def __init__(self, client: httpx.Client | None = None, mailto: str | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)
        self.mailto = mailto

    def search(self, query: str, limit: int = 25) -> list[Paper]:
        params: dict[str, str | int] = {"search": query, "per-page": min(limit, 100)}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            response = self.client.get("https://api.openalex.org/works", params=params)
            response.raise_for_status()
            results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError) as error:
            raise SourceError(f"OpenAlex search failed: {error}") from error
        return [self._paper(item, query, rank) for rank, item in enumerate(results, start=1)]

    def _paper(self, item: dict[str, Any], query: str, rank: int) -> Paper:
        doi = item.get("doi")
        if isinstance(doi, str):
            doi = doi.removeprefix(DOI_PREFIX).lower()
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        abstract = _decode_abstract(item.get("abstract_inverted_index"))
        fulltext_candidates = _openalex_fulltext_candidates(item)
        return Paper(
            id=str(item["id"]),
            title=_clean(item.get("display_name") or "Untitled work"),
            authors=[
                _clean(authorship.get("author", {}).get("display_name", "Unknown"))
                for authorship in item.get("authorships", [])
            ],
            abstract=_clean(abstract) if abstract else None,
            year=item.get("publication_year"),
            publication_date=_parse_date(item.get("publication_date")),
            venue=_optional_clean(source.get("display_name")),
            doi=doi,
            url=location.get("landing_page_url") or item.get("id"),
            cited_by_count=item.get("cited_by_count") or 0,
            open_access=(item.get("open_access") or {}).get("is_oa"),
            sources={self.name},
            queries={query},
            source_ranks=[rank],
            fulltext_candidates=fulltext_candidates,
        )


class ArxivSource(ScholarlySource):
    name = "arxiv"
    namespace: ClassVar[dict[str, str]] = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)

    def search(self, query: str, limit: int = 25) -> list[Paper]:
        url = (
            "https://export.arxiv.org/api/query?search_query=all:"
            f"{quote(query)}&start=0&max_results={min(limit, 100)}&sortBy=relevance"
        )
        try:
            response = self.client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except (httpx.HTTPError, ET.ParseError) as error:
            raise SourceError(f"arXiv search failed: {error}") from error
        papers: list[Paper] = []
        for rank, entry in enumerate(root.findall("atom:entry", self.namespace), start=1):
            identifier = _text(entry, "atom:id", self.namespace).rsplit("/", 1)[-1]
            published = _text(entry, "atom:published", self.namespace)
            authors = [
                _text(author, "atom:name", self.namespace)
                for author in entry.findall("atom:author", self.namespace)
            ]
            papers.append(
                Paper(
                    id=f"arxiv:{identifier}",
                    arxiv_id=identifier,
                    title=_clean(" ".join(_text(entry, "atom:title", self.namespace).split())),
                    authors=[_clean(author) for author in authors],
                    abstract=_clean(" ".join(_text(entry, "atom:summary", self.namespace).split())),
                    year=int(published[:4]) if published else None,
                    publication_date=_parse_date(published[:10]),
                    url=_text(entry, "atom:id", self.namespace),
                    sources={self.name},
                    queries={query},
                    source_ranks=[rank],
                    fulltext_candidates=[
                        FullTextCandidate(
                            url=f"https://arxiv.org/pdf/{identifier}",
                            source="arxiv",
                            version="submitted manuscript",
                        )
                    ],
                )
            )
        return papers


class CrossrefSource:
    name = "crossref"

    def __init__(self, client: httpx.Client | None = None, mailto: str | None = None) -> None:
        headers = {"User-Agent": f"RAGdoll/1.0 ({mailto or 'no-contact'})"}
        self.client = client or httpx.Client(timeout=30, headers=headers)

    def enrich(self, paper: Paper) -> Paper:
        if not paper.doi:
            return paper
        try:
            response = self.client.get(f"https://api.crossref.org/works/{quote(paper.doi)}")
            response.raise_for_status()
            message = response.json()["message"]
        except (httpx.HTTPError, ValueError, KeyError):
            return paper
        update: dict[str, Any] = {"sources": paper.sources | {self.name}}
        if not paper.venue:
            containers = message.get("container-title") or []
            update["venue"] = containers[0] if containers else None
        if not paper.url and message.get("URL"):
            update["url"] = message["URL"]
        return paper.model_copy(update=update)


def search_all(
    sources: list[ScholarlySource], queries: list[str], limit: int = 25
) -> tuple[list[Paper], list[str]]:
    papers: list[Paper] = []
    warnings: list[str] = []
    for query in queries:
        for source in sources:
            try:
                papers.extend(source.search(query, limit))
            except SourceError as error:
                warnings.append(str(error))
            time.sleep(0.05)
    return papers, warnings


def _decode_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(words))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text(element: Element, path: str, namespace: dict[str, str]) -> str:
    found = element.find(path, namespace)
    return found.text.strip() if found is not None and found.text else ""


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def _clean(value: str) -> str:
    """Remove terminal control characters from untrusted scholarly metadata."""
    return "".join(character for character in value if character in "\n\t" or ord(character) >= 32)


def _optional_clean(value: object) -> str | None:
    return _clean(value) if isinstance(value, str) and value else None


def _openalex_fulltext_candidates(item: dict[str, Any]) -> list[FullTextCandidate]:
    locations = [item.get("best_oa_location"), item.get("primary_location")]
    locations.extend(item.get("locations") or [])
    candidates: list[FullTextCandidate] = []
    seen: set[str] = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        url = location.get("pdf_url")
        if not isinstance(url, str) or not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        candidates.append(
            FullTextCandidate(
                url=url,
                source="openalex",
                license=_optional_clean(location.get("license")),
                version=_optional_clean(location.get("version")),
            )
        )
    return candidates
