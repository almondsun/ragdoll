"""Reproducible investigation exports."""

from __future__ import annotations

import re
from pathlib import Path

from .domain import EvidenceChunk, GroundedAnswer, Investigation, RankedPaper, ResearchDossier
from .safe_io import atomic_write


def export_investigation(investigation: Investigation, output: Path, format: str) -> Path:
    if format == "json":
        content = investigation.model_dump_json(indent=2)
    elif format == "markdown":
        content = _markdown(investigation)
    elif format == "bibtex":
        content = _bibtex(investigation.papers)
    else:
        raise ValueError(f"unsupported export format: {format}")
    atomic_write(output, content.encode())
    return output


def _markdown(investigation: Investigation) -> str:
    lines = [
        f"# {investigation.plan.title if investigation.plan else investigation.original_prompt}",
        "",
    ]
    lines.extend(
        ["## Research brief", "", investigation.brief.objective if investigation.brief else "", ""]
    )
    if investigation.plan:
        lines.extend(["## Investigation axes", ""])
        lines.extend(f"- {axis}" for axis in investigation.plan.investigation_axes)
        lines.extend(["", "## Queries", ""])
        lines.extend(
            f"- **{family.axis}:** `{family.query}` — {family.rationale}"
            for family in investigation.plan.query_families
        )
    lines.extend(["", "## Staged papers", ""])
    for index, item in enumerate((paper for paper in investigation.papers if paper.staged), 1):
        paper = item.paper
        availability = "abstract available" if paper.abstract else "metadata only"
        lines.extend(
            [
                f"### {index}. {paper.title}",
                "",
                f"- Authors: {', '.join(paper.authors) or 'Unknown'}",
                f"- Year: {paper.year or 'Unknown'}",
                f"- Sources: {', '.join(sorted(paper.sources))}",
                f"- Evidence available to RAGdoll: {availability}",
                f"- Score: {item.score:.3f}",
                f"- Why staged: {item.rationale}",
                f"- URL: {paper.url or 'Unavailable'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Provenance and limitations",
            "",
            (
                "RAGdoll searched the declared scholarly indexes using the queries above. "
                "The collection is bounded by index coverage and retrieval time; it is not "
                "an exhaustive statement of the literature."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _bibtex(papers: list[RankedPaper]) -> str:
    entries: list[str] = []
    for item in papers:
        if not item.staged:
            continue
        paper = item.paper
        first_author = paper.authors[0].split()[-1] if paper.authors else "unknown"
        key = re.sub(r"\W+", "", f"{first_author}{paper.year or ''}{paper.title[:12]}").lower()
        fields = {
            "title": paper.title,
            "author": " and ".join(paper.authors),
            "year": str(paper.year or ""),
            "url": str(paper.url or ""),
        }
        if paper.doi:
            fields["doi"] = paper.doi
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields.items() if value)
        entries.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def export_dossier(
    dossier: ResearchDossier,
    investigation: Investigation,
    chunks: dict[str, EvidenceChunk],
    output: Path,
    format: str,
) -> Path:
    if format == "json":
        payload = {
            "dossier": dossier.model_dump(mode="json"),
            "citations": {
                chunk_id: chunk.model_dump(mode="json") for chunk_id, chunk in chunks.items()
            },
        }
        import json

        content = json.dumps(payload, indent=2)
    elif format == "markdown":
        content = render_dossier(dossier, investigation, chunks)
    else:
        raise ValueError(f"unsupported dossier format: {format}")
    atomic_write(output, content.encode())
    return output


def render_answer(answer: GroundedAnswer, chunks: dict[str, EvidenceChunk]) -> str:
    lines = [f"## {answer.question}", ""]
    if answer.insufficient_evidence:
        lines.extend([f"**Insufficient evidence:** {answer.explanation}", ""])
    else:
        for claim in answer.claims:
            lines.extend([f"- {claim.text} {_citations(claim.chunk_ids, chunks)}", ""])
    return "\n".join(lines)


def render_dossier(
    dossier: ResearchDossier,
    investigation: Investigation,
    chunks: dict[str, EvidenceChunk],
) -> str:
    papers = {item.paper.id: item.paper for item in investigation.papers}
    lines = [
        f"# {dossier.title}",
        "",
        f"**Evidence coverage:** {dossier.evidence_summary}",
        "",
        (
            "This dossier is bounded by the approved search, staged corpus, retrieval time, and "
            "available evidence. It does not establish exhaustive coverage or novelty."
        ),
        "",
    ]
    for section in dossier.sections:
        lines.extend([f"## {section.title}", ""])
        if not section.claims:
            lines.extend(["No sufficiently grounded claim was produced for this section.", ""])
        for claim in section.claims:
            lines.extend([f"- {claim.text} {_citations(claim.chunk_ids, chunks)}", ""])
    lines.extend(["## References", ""])
    referenced = {chunks[chunk_id].paper_id for chunk_id in chunks}
    for index, item in enumerate(investigation.papers, 1):
        paper = papers[item.paper.id]
        if paper.id in referenced:
            lines.append(
                f"{index}. {', '.join(paper.authors) or 'Unknown'}. "
                f"**{paper.title}** ({paper.year or 'n.d.'}). {paper.url or ''}"
            )
    lines.append("")
    return "\n".join(lines)


def _citations(chunk_ids: list[str], chunks: dict[str, EvidenceChunk]) -> str:
    rendered = []
    for chunk_id in chunk_ids:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            rendered.append(f"[{chunk_id}: unavailable]")
        else:
            rendered.append(f"[{chunk.paper_id}, {chunk.locator}; `{chunk.id}`]")
    return " ".join(rendered)
