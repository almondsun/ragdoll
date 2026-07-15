# RAGdoll

RAGdoll is an explainable terminal workspace for turning a fuzzy research interest into a curated
paper collection. Its central design choice is to separate **clarification**, **plan approval**, and
**execution** rather than immediately generating a broad report.

## Guarantees

- Search begins only after the user approves the plan.
- Every clarification presents three proposed answers plus custom input.
- Every discovered work retains query and source provenance.
- Ranking exposes components and a bounded model judgment.
- Metadata-only records are never described as read papers.

Start with the [planning contract](planning-contract.md), then read the
[architecture](architecture.md) and [retrieval methodology](retrieval-and-ranking.md).
