"""Capture the sealed three-arm benchmark using live scholarly sources and a provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from ragdoll import __version__
from ragdoll.config import Settings, load_settings
from ragdoll.domain import (
    ClarificationAnswer,
    Investigation,
    InvestigationStatus,
    ResearchBrief,
)
from ragdoll.planning import Planner
from ragdoll.providers import ModelProvider, make_provider
from ragdoll.safe_io import atomic_write
from ragdoll.service import ResearchService
from ragdoll.sources import OpenAlexSource, search_all

T = TypeVar("T", bound=BaseModel)


class CountingProvider:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider
        self.calls = 0

    def structured(
        self,
        *,
        instructions: str,
        prompt: str,
        response_model: type[T],
        quality: bool = False,
    ) -> T:
        self.calls += 1
        return self.provider.structured(
            instructions=instructions,
            prompt=prompt,
            response_model=response_model,
            quality=quality,
        )


def collect(
    topics: list[dict[str, object]],
    root: Path,
    provider_name: str,
    capture: dict[str, Any] | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    settings = load_settings(root, provider=provider_name)
    provider = CountingProvider(make_provider(settings))
    topics_checksum = hashlib.sha256(
        json.dumps(topics, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    environment = {
        "ragdoll_version": __version__,
        "git_commit": _clean_git_commit(root, checkpoint_path),
        "python": platform.python_version(),
        "provider": provider_name,
        "model": settings.ollama_model
        if provider_name == "ollama"
        else settings.openai_model_quality,
        "model_identity": _model_identity(settings, provider_name),
        "endpoint": settings.ollama_url if provider_name == "ollama" else "https://api.openai.com",
        "topics_sha256": topics_checksum,
        "evaluation_contract": "three-arm-v2.2-staged20-production-ranking",
    }
    if capture is None:
        capture = {
            "schema_version": 1,
            "captured_at": datetime.now(UTC).isoformat(),
            "environment": environment,
            "topics": {},
        }
    if capture.get("environment") != environment:
        raise ValueError("existing capture uses a different sealed run environment")
    results: dict[str, Any] = capture["topics"]
    for topic in topics:
        topic_id = str(topic["id"])
        result = results.setdefault(topic_id, {"arms": {}})
        arms = result["arms"]
        if "raw_openalex" not in arms:
            started = time.perf_counter()
            raw, warnings = search_all(
                [OpenAlexSource(mailto=settings.openalex_mailto)],
                [str(topic["prompt"])],
                limit=20,
                date_from=_date(topic.get("date_from")),
                date_to=_date(topic.get("date_to")),
            )
            arms["raw_openalex"] = {
                "papers": [paper.model_dump(mode="json") for paper in raw],
                "queries": [str(topic["prompt"])],
                "warnings": warnings,
                "latency_seconds": time.perf_counter() - started,
                "provider_calls": 0,
            }
            if checkpoint:
                checkpoint(capture)
        for arm, answers in (
            ("planned", []),
            ("full_workflow", [_benchmark_answer(topic)]),
        ):
            if arm in arms:
                continue
            before_calls = provider.calls
            started = time.perf_counter()
            planner = Planner(provider)
            brief = planner.build_brief(str(topic["prompt"]), answers)
            brief = _apply_topic_contract(brief, topic)
            plan = planner.build_plan(brief).model_copy(
                update={"sources": topic.get("sources", ["openalex", "arxiv"])}
            )
            now = datetime.now(UTC)
            investigation = Investigation(
                id=f"eval-{topic_id}-{arm}",
                created_at=now,
                updated_at=now,
                status=InvestigationStatus.PLAN_REVIEW,
                original_prompt=str(topic["prompt"]),
                answers=answers,
                brief=brief,
                plan=plan,
            )
            with tempfile.TemporaryDirectory(prefix="ragdoll-eval-") as directory:
                service = ResearchService(Path(directory), settings, provider)
                service.workspace.save(investigation, "benchmark_created")
                service.approve_plan(investigation)
                completed, warnings = service.execute(investigation)
            arms[arm] = {
                "papers": [
                    item.paper.model_dump(mode="json") for item in completed.papers if item.staged
                ],
                "queries": [family.query for family in plan.query_families],
                "warnings": warnings,
                "latency_seconds": time.perf_counter() - started,
                "provider_calls": provider.calls - before_calls,
            }
            if checkpoint:
                checkpoint(capture)
    return capture


def _benchmark_answer(topic: dict[str, object]) -> ClarificationAnswer:
    axes = ", ".join(str(axis) for axis in topic["axes"])  # type: ignore[union-attr]
    return ClarificationAnswer(
        question_id="benchmark_scope",
        question="What evidence and comparison dimensions should guide this investigation?",
        answer=f"Primary scholarship addressing these fixed axes: {axes}.",
        option_labels=["Fixed benchmark scope"],
    )


def _apply_topic_contract(brief: ResearchBrief, topic: dict[str, object]) -> ResearchBrief:
    return brief.model_copy(
        update={
            "date_from": _date(topic.get("date_from")) or brief.date_from,
            "date_to": _date(topic.get("date_to")) or brief.date_to,
            "desired_paper_count": 20,
        }
    )


def _date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _clean_git_commit(root: Path, checkpoint_path: Path | None = None) -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    allowed: set[str] = set()
    temporary_prefix: str | None = None
    if checkpoint_path is not None:
        try:
            relative = checkpoint_path.resolve().relative_to(root.resolve()).as_posix()
            allowed.add(relative)
            temporary_prefix = str(Path(relative).parent / f".{checkpoint_path.name}-")
        except ValueError:
            pass
    dirty = []
    for line in status.stdout.splitlines():
        path = line[3:]
        if path in allowed or (temporary_prefix and path.startswith(temporary_prefix)):
            continue
        dirty.append(line)
    if dirty:
        raise ValueError("sealed benchmark capture requires a clean Git worktree")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _model_identity(settings: Settings, provider_name: str) -> str:
    if provider_name != "ollama":
        return settings.openai_model_quality
    url = settings.ollama_url
    model = settings.ollama_model
    response = httpx.get(f"{url}/api/tags", timeout=10, trust_env=False)
    response.raise_for_status()
    expected = model.removesuffix(":latest")
    for item in response.json().get("models", []):
        if str(item.get("name", "")).removesuffix(":latest") == expected:
            return str(item.get("digest") or item.get("id") or model)
    raise ValueError(f"Ollama model is not installed: {model}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", type=Path, default=Path(__file__).with_name("topics.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    topics = json.loads(args.topics.read_text(encoding="utf-8"))
    existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else None

    def save(value: dict[str, Any]) -> None:
        atomic_write(args.output, (json.dumps(value, indent=2) + "\n").encode())

    result = collect(topics, args.root, args.provider, existing, save, checkpoint_path=args.output)
    save(result)


if __name__ == "__main__":
    main()
