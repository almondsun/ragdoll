from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


def module():
    path = Path(__file__).parents[1] / "evals" / "run.py"
    spec = importlib.util.spec_from_file_location("ragdoll_evals", path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def collector_module():
    path = Path(__file__).parents[1] / "evals" / "collect.py"
    spec = importlib.util.spec_from_file_location("ragdoll_collect", path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_evaluation_metrics() -> None:
    evaluation = module()
    assert evaluation.normalized("A: Paper!") == "apaper"
    assert evaluation.recall_at(["Known paper"], ["Known Paper"]) == 1
    assert evaluation.recall_at([], []) == 1
    assert evaluation.ndcg_at([3, 2, 0]) == 1
    assert evaluation.ndcg_at([]) == 1
    assert evaluation.ndcg_at([0, 3]) < 1
    assert evaluation.ndcg_at([3], ideal_relevances=[4, 3]) < 1


def test_blinded_worksheet_and_release_gate() -> None:
    evaluation = module()
    topics = [
        {
            "id": "topic",
            "axes": ["architecture"],
            "known_titles": ["Known paper"],
            "sources": ["openalex"],
        }
    ]
    paper = {
        "id": "https://openalex.org/W1",
        "title": "Known paper",
        "authors": ["Ada"],
        "year": 2024,
        "publication_date": "2024-01-01",
        "retrieval_hits": [
            {
                "source": "openalex",
                "source_id": "https://openalex.org/W1",
                "query": "known",
                "rank": 1,
            }
        ],
    }
    capture = {"topics": {"topic": {"arms": {arm: {"papers": [paper]} for arm in evaluation.ARMS}}}}
    worksheet = evaluation.prepare_worksheet(capture, topics)
    assert "arm" not in worksheet["rows"][0]
    with pytest.raises(ValueError, match="adjudication"):
        evaluation.score_capture(capture, topics, worksheet)
    worksheet["adjudicated_by"] = "maintainer"
    worksheet["adjudicated_at"] = "2026-07-16T00:00:00Z"
    worksheet["rows"][0]["relevance_0_to_4"] = 4
    worksheet["rows"][0]["covered_axes"] = ["architecture"]
    report = evaluation.score_capture(capture, topics, worksheet)
    assert report["release_pass"] is True
    assert all(report["gates"].values())
    assert report["summary"]["full_workflow"]["total_provider_calls"] == 0
    assert "abstract" in worksheet["rows"][0]


def test_incomplete_capture_cannot_be_adjudicated() -> None:
    evaluation = module()
    topics = [{"id": "topic", "axes": ["axis"], "known_titles": []}]
    with pytest.raises(ValueError, match="incomplete"):
        evaluation.prepare_worksheet({"topics": {}}, topics)


def test_qrels_merge_preprint_and_published_aliases() -> None:
    evaluation = module()
    topics = [{"id": "topic", "axes": ["axis"], "known_titles": []}]
    preprint = {
        "id": "arxiv:2401.00001v2",
        "arxiv_id": "2401.00001v2",
        "title": "One Paper",
        "authors": ["Ada Author"],
    }
    published = {
        "id": "https://openalex.org/W1",
        "doi": "10.1/paper",
        "title": "One Paper",
        "authors": ["Ada Author"],
    }
    capture = {
        "topics": {
            "topic": {
                "arms": {
                    "raw_openalex": {"papers": [published]},
                    "planned": {"papers": [preprint]},
                    "full_workflow": {"papers": [published]},
                }
            }
        }
    }
    worksheet = evaluation.prepare_worksheet(capture, topics)
    assert len(worksheet["rows"]) == 1


def test_sealed_capture_allows_only_its_checkpoint_to_be_dirty(tmp_path: Path) -> None:
    collector = collector_module()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    checkpoint = tmp_path / "evals" / "results" / "capture.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}", encoding="utf-8")
    assert collector._clean_git_commit(tmp_path, checkpoint)
    tracked.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="clean Git"):
        collector._clean_git_commit(tmp_path, checkpoint)
