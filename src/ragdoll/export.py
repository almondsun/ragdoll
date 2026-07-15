"""Reproducible investigation exports."""

from __future__ import annotations

import re
from pathlib import Path

from .domain import Investigation, RankedPaper


def export_investigation(investigation: Investigation, output: Path, format: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        output.write_text(investigation.model_dump_json(indent=2), encoding="utf-8")
    elif format == "markdown":
        output.write_text(_markdown(investigation), encoding="utf-8")
    elif format == "bibtex":
        output.write_text(_bibtex(investigation.papers), encoding="utf-8")
    else:
        raise ValueError(f"unsupported export format: {format}")
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
