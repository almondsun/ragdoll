"""Score an exported RAGdoll benchmark run without live network access."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def normalized(title: str) -> str:
    return "".join(character for character in title.casefold() if character.isalnum())


def recall_at(titles: list[str], expected: list[str], limit: int = 20) -> float:
    if not expected:
        return 1.0
    observed = {normalized(title) for title in titles[:limit]}
    return sum(normalized(title) in observed for title in expected) / len(expected)


def ndcg_at(relevances: list[int], limit: int = 15) -> float:
    def dcg(values: list[int]) -> float:
        return sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(values))

    actual = dcg(relevances[:limit])
    ideal = dcg(sorted(relevances, reverse=True)[:limit])
    return actual / ideal if ideal else 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path, help="JSON mapping topic IDs to ranked titles/relevances")
    parser.add_argument("--topics", type=Path, default=Path(__file__).with_name("topics.json"))
    args = parser.parse_args()
    topics = json.loads(args.topics.read_text(encoding="utf-8"))
    run = json.loads(args.run.read_text(encoding="utf-8"))
    scores = []
    for topic in topics:
        result = run.get(topic["id"], {})
        recall = recall_at(result.get("titles", []), topic["known_titles"])
        ndcg = ndcg_at(result.get("relevances", []))
        scores.append((recall, ndcg))
        print(f"{topic['id']}: recall@20={recall:.3f} ndcg@15={ndcg:.3f}")
    print(f"mean recall@20={sum(score[0] for score in scores) / len(scores):.3f}")
    print(f"mean ndcg@15={sum(score[1] for score in scores) / len(scores):.3f}")


if __name__ == "__main__":
    main()
