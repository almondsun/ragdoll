"""Prepare blinded judgments and score a captured three-arm benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from ragdoll.safe_io import atomic_write

ARMS = ("raw_openalex", "planned", "full_workflow")
GATES = {
    "recall_at_20": 0.75,
    "ndcg_at_15": 0.70,
    "axis_coverage": 0.90,
    "duplicate_rate_max": 0.01,
    "constraint_compliance": 1.0,
    "unauditable_identifiers_max": 0,
}


def normalized(title: str) -> str:
    return "".join(character for character in title.casefold() if character.isalnum())


def recall_at(titles: list[str], expected: list[str], limit: int = 20) -> float:
    if not expected:
        return 1.0
    observed = {normalized(title) for title in titles[:limit]}
    return sum(normalized(title) in observed for title in expected) / len(expected)


def ndcg_at(
    relevances: list[int], limit: int = 15, ideal_relevances: list[int] | None = None
) -> float:
    def dcg(values: list[int]) -> float:
        return sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(values))

    actual = dcg(relevances[:limit])
    ideal = dcg(sorted(ideal_relevances or relevances, reverse=True)[:limit])
    return actual / ideal if ideal else 1.0


def candidate_key(paper: dict[str, Any]) -> str:
    identity = str(paper.get("doi") or paper.get("arxiv_id") or paper.get("id") or "")
    return hashlib.sha256(f"{identity}\0{paper.get('title', '')}".encode()).hexdigest()[:16]


def prepare_worksheet(capture: dict[str, Any], topics: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_complete_capture(capture, topics)
    rows: list[dict[str, Any]] = []
    topic_map = {topic["id"]: topic for topic in topics}
    for topic_id, result in sorted(capture["topics"].items()):
        topic = topic_map[topic_id]
        identities = _canonical_candidate_ids(result)
        candidates: dict[str, dict[str, Any]] = {}
        for arm in ARMS:
            for paper in result["arms"][arm]["papers"]:
                candidates.setdefault(identities[candidate_key(paper)], paper)
        for key, paper in sorted(candidates.items(), key=lambda item: normalized(item[1]["title"])):
            rows.append(
                {
                    "topic_id": topic_id,
                    "candidate_id": key,
                    "title": paper["title"],
                    "authors": paper.get("authors", []),
                    "year": paper.get("year"),
                    "abstract": (paper.get("abstract") or "")[:1500],
                    "venue": paper.get("venue"),
                    "doi": paper.get("doi"),
                    "arxiv_id": paper.get("arxiv_id"),
                    "source_ids": sorted(
                        {
                            str(hit.get("source_id"))
                            for hit in paper.get("retrieval_hits", [])
                            if hit.get("source_id")
                        }
                    ),
                    "topic_axes": topic["axes"],
                    "relevance_0_to_4": None,
                    "covered_axes": [],
                    "notes": "",
                }
            )
    return {
        "capture_sha256": _sha256(capture),
        "adjudicated_by": None,
        "adjudicated_at": None,
        "rows": rows,
    }


def score_capture(
    capture: dict[str, Any], topics: list[dict[str, Any]], worksheet: dict[str, Any]
) -> dict[str, Any]:
    _validate_complete_capture(capture, topics)
    if worksheet.get("capture_sha256") != _sha256(capture):
        raise ValueError("worksheet does not match this captured run")
    if not worksheet.get("adjudicated_by") or not worksheet.get("adjudicated_at"):
        raise ValueError("maintainer adjudication and timestamp are required before scoring")
    judgments: dict[tuple[str, str], dict[str, Any]] = {}
    for row in worksheet["rows"]:
        relevance = row.get("relevance_0_to_4")
        if not isinstance(relevance, int) or not 0 <= relevance <= 4:
            raise ValueError(f"candidate {row.get('candidate_id')} lacks a 0-4 relevance label")
        judgments[(row["topic_id"], row["candidate_id"])] = row
    topic_map = {topic["id"]: topic for topic in topics}
    per_arm: dict[str, list[dict[str, float | int]]] = defaultdict(list)
    for topic_id, result in capture["topics"].items():
        topic = topic_map[topic_id]
        identities = _canonical_candidate_ids(result)
        ideal_relevances = [
            row["relevance_0_to_4"]
            for (judged_topic, _candidate), row in judgments.items()
            if judged_topic == topic_id
        ]
        for arm in ARMS:
            papers = result["arms"][arm]["papers"]
            rows = [judgments[(topic_id, identities[candidate_key(paper)])] for paper in papers]
            covered = {axis for row in rows for axis in row["covered_axes"]}
            duplicates = _duplicate_count(papers)
            compliant = sum(_compliant(paper, topic) for paper in papers)
            unauditable = sum(not _has_auditable_identifier(paper) for paper in papers)
            per_arm[arm].append(
                {
                    "recall_at_20": recall_at(
                        [paper["title"] for paper in papers], topic["known_titles"]
                    ),
                    "ndcg_at_15": ndcg_at(
                        [row["relevance_0_to_4"] for row in rows],
                        ideal_relevances=ideal_relevances,
                    ),
                    "axis_coverage": len(covered & set(topic["axes"])) / len(topic["axes"]),
                    "duplicates": duplicates,
                    "papers": len(papers),
                    "compliant": compliant,
                    "unauditable_identifiers": unauditable,
                    "latency_seconds": float(result["arms"][arm].get("latency_seconds", 0.0)),
                    "provider_calls": int(result["arms"][arm].get("provider_calls", 0)),
                }
            )
    summary = {arm: _summarize(values) for arm, values in per_arm.items()}
    full = summary["full_workflow"]
    gates = {
        "recall_at_20": full["recall_at_20"] >= GATES["recall_at_20"],
        "ndcg_at_15": full["ndcg_at_15"] >= GATES["ndcg_at_15"],
        "axis_coverage": full["axis_coverage"] >= GATES["axis_coverage"],
        "duplicate_rate": full["duplicate_rate"] < GATES["duplicate_rate_max"],
        "constraint_compliance": (full["constraint_compliance"] == GATES["constraint_compliance"]),
        "identifier_auditability": (
            full["unauditable_identifiers"] == GATES["unauditable_identifiers_max"]
        ),
    }
    return {
        "capture_sha256": _sha256(capture),
        "adjudication": {
            "by": worksheet["adjudicated_by"],
            "at": worksheet["adjudicated_at"],
        },
        "summary": summary,
        "gates": gates,
        "release_pass": all(gates.values()),
    }


def _summarize(values: list[dict[str, float | int]]) -> dict[str, float | int]:
    papers = sum(int(value["papers"]) for value in values)
    return {
        "recall_at_20": _mean(values, "recall_at_20"),
        "ndcg_at_15": _mean(values, "ndcg_at_15"),
        "axis_coverage": _mean(values, "axis_coverage"),
        "duplicate_rate": sum(int(value["duplicates"]) for value in values) / papers
        if papers
        else 0.0,
        "constraint_compliance": sum(int(value["compliant"]) for value in values) / papers
        if papers
        else 1.0,
        "unauditable_identifiers": sum(int(value["unauditable_identifiers"]) for value in values),
        "mean_latency_seconds": _mean(values, "latency_seconds"),
        "p50_latency_seconds": _percentile(values, "latency_seconds", 0.50),
        "p95_latency_seconds": _percentile(values, "latency_seconds", 0.95),
        "total_provider_calls": sum(int(value["provider_calls"]) for value in values),
        "mean_provider_calls": _mean(values, "provider_calls"),
    }


def _mean(values: list[dict[str, float | int]], key: str) -> float:
    return sum(float(value[key]) for value in values) / len(values) if values else 0.0


def _percentile(values: list[dict[str, float | int]], key: str, percentile: float) -> float:
    ordered = sorted(float(value[key]) for value in values)
    if not ordered:
        return 0.0
    index = math.ceil(percentile * len(ordered)) - 1
    return ordered[max(index, 0)]


def _compliant(paper: dict[str, Any], topic: dict[str, Any]) -> bool:
    publication = paper.get("publication_date")
    if topic.get("date_from") or topic.get("date_to"):
        if not publication:
            return False
        observed = date.fromisoformat(publication)
        if topic.get("date_from") and observed < date.fromisoformat(topic["date_from"]):
            return False
        if topic.get("date_to") and observed > date.fromisoformat(topic["date_to"]):
            return False
    allowed = set(topic.get("sources", ["openalex", "arxiv"]))
    hits = paper.get("retrieval_hits", [])
    return bool(hits) and all(hit.get("source") in allowed for hit in hits)


def _has_auditable_identifier(paper: dict[str, Any]) -> bool:
    if not paper.get("id"):
        return False
    hits = paper.get("retrieval_hits", [])
    if not hits:
        return False
    for hit in hits:
        source = hit.get("source")
        source_id = str(hit.get("source_id") or "")
        if not hit.get("query") or not isinstance(hit.get("rank"), int) or hit["rank"] < 1:
            return False
        if source == "openalex":
            if not re.fullmatch(r"https://openalex\.org/W\d+", source_id):
                return False
        elif source == "arxiv":
            if not re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?|[a-z-]+/\d{7}(v\d+)?", source_id):
                return False
        else:
            return False
    aliases = _paper_aliases(paper)
    return any(
        f"arxiv:{str(hit['source_id']).split('v', 1)[0].casefold()}" in aliases
        or str(hit["source_id"]) == str(paper["id"])
        for hit in hits
    )


def _duplicate_count(papers: list[dict[str, Any]]) -> int:
    groups: list[set[str]] = []
    for paper in papers:
        aliases = _paper_aliases(paper)
        matches = [index for index, known in enumerate(groups) if known & aliases]
        if not matches:
            groups.append(aliases)
            continue
        first = matches[0]
        for index in reversed(matches[1:]):
            groups[first] |= groups.pop(index)
        groups[first] |= aliases
    return len(papers) - len(groups)


def _paper_aliases(paper: dict[str, Any]) -> set[str]:
    aliases = {
        "title:"
        + normalized(str(paper.get("title", "")))
        + ":"
        + normalized(str((paper.get("authors") or [""])[0]))
    }
    if paper.get("doi"):
        aliases.add(f"doi:{str(paper['doi']).casefold()}")
    if paper.get("arxiv_id"):
        aliases.add(f"arxiv:{str(paper['arxiv_id']).split('v', 1)[0].casefold()}")
    return aliases


def _canonical_candidate_ids(result: dict[str, Any]) -> dict[str, str]:
    groups: list[tuple[set[str], set[str]]] = []
    for arm in ARMS:
        for paper in result["arms"][arm]["papers"]:
            aliases = _paper_aliases(paper)
            base = candidate_key(paper)
            matches = [index for index, (known, _bases) in enumerate(groups) if known & aliases]
            if not matches:
                groups.append((aliases, {base}))
                continue
            first = matches[0]
            known, bases = groups[first]
            for index in reversed(matches[1:]):
                other_known, other_bases = groups.pop(index)
                known |= other_known
                bases |= other_bases
            groups[first] = (known | aliases, bases | {base})
    identities: dict[str, str] = {}
    for aliases, bases in groups:
        canonical = hashlib.sha256("\0".join(sorted(aliases)).encode()).hexdigest()[:16]
        identities.update(dict.fromkeys(bases, canonical))
    return identities


def _validate_complete_capture(capture: dict[str, Any], topics: list[dict[str, Any]]) -> None:
    expected = {topic["id"] for topic in topics}
    observed = set(capture.get("topics", {}))
    if observed != expected:
        raise ValueError("capture is incomplete or contains unexpected topics")
    for topic_id in expected:
        arms = capture["topics"][topic_id].get("arms", {})
        if set(arms) != set(ARMS):
            raise ValueError(f"capture is incomplete for topic {topic_id}")


def _sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--topics", type=Path, default=Path(__file__).with_name("topics.json"))
    parser.add_argument("--prepare", type=Path, help="write a blinded adjudication worksheet")
    parser.add_argument("--judgments", type=Path, help="score a completed adjudication worksheet")
    parser.add_argument("--output", type=Path, help="write the score report as JSON")
    args = parser.parse_args()
    topics = json.loads(args.topics.read_text(encoding="utf-8"))
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    if args.prepare:
        atomic_write(
            args.prepare,
            (json.dumps(prepare_worksheet(capture, topics), indent=2) + "\n").encode(),
        )
        return
    if not args.judgments:
        parser.error("provide --prepare or --judgments")
    worksheet = json.loads(args.judgments.read_text(encoding="utf-8"))
    report = score_capture(capture, topics, worksheet)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        atomic_write(args.output, rendered.encode())
    else:
        print(rendered, end="")
    if not report["release_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
