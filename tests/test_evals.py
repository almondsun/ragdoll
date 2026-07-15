from __future__ import annotations

import importlib.util
from pathlib import Path


def module():
    path = Path(__file__).parents[1] / "evals" / "run.py"
    spec = importlib.util.spec_from_file_location("ragdoll_evals", path)
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
