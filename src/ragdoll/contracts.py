"""Canonical fingerprints for approval and derived-state contracts."""

from __future__ import annotations

import hashlib
import json

from .domain import EvidenceDocument, Investigation


def plan_fingerprint(investigation: Investigation) -> str:
    if investigation.brief is None or investigation.plan is None:
        raise ValueError("a brief and plan are required")
    return _fingerprint(
        {
            "brief": investigation.brief.model_dump(mode="json"),
            "plan": investigation.plan.model_dump(mode="json"),
        }
    )


def staged_fingerprint(investigation: Investigation) -> str:
    staged: list[dict[str, object]] = [
        {
            "id": item.paper.id,
            "doi": item.paper.doi,
            "arxiv_id": item.paper.arxiv_id,
            "title": item.paper.title,
            "abstract": item.paper.abstract,
            "fulltext_candidates": [
                candidate.model_dump(mode="json") for candidate in item.paper.fulltext_candidates
            ],
        }
        for item in investigation.papers
        if item.staged
    ]
    return _fingerprint(sorted(staged, key=lambda item: str(item["id"])))


def evidence_fingerprint(
    investigation: Investigation,
    documents: list[EvidenceDocument],
    paper_ids: set[str] | None = None,
    acquisition_fingerprint: str | None = None,
) -> str:
    staged_ids = paper_ids or {item.paper.id for item in investigation.papers if item.staged}
    relevant: list[dict[str, str | None]] = [
        {
            "paper_id": document.paper_id,
            "sha256": document.sha256,
            "level": document.evidence_level.value,
            "status": document.status.value,
        }
        for document in sorted(documents, key=lambda item: item.paper_id)
        if document.paper_id in staged_ids
        and (
            acquisition_fingerprint is None
            or document.staged_fingerprint == acquisition_fingerprint
        )
    ]
    return _fingerprint(
        {
            "staged": staged_fingerprint(investigation),
            "acquisition": acquisition_fingerprint,
            "documents": relevant,
        }
    )


def inference_fingerprint(investigation: Investigation, details: dict[str, str]) -> str:
    return _fingerprint({"staged": staged_fingerprint(investigation), "inference": details})


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()
