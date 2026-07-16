# RAGdoll

RAGdoll is an explainable terminal workspace for turning a fuzzy research interest into a curated,
cited research dossier. Its central design choice is to keep **clarification**, **search approval**,
**human curation**, and **evidence-acquisition approval** as separate boundaries.

## Guarantees

- Search begins only after the user approves the plan.
- Every clarification presents three proposed answers plus custom input.
- Every discovered work retains query and source provenance.
- Ranking exposes components and a bounded model judgment.
- Metadata-only records are never described as read papers.
- Open PDFs are downloaded only after an explicit preview and confirmation.
- Every generated factual claim cites one or more indexed passages.
- Unsupported questions return an explicit insufficient-evidence result.

Start with the [planning contract](planning-contract.md), then read the
[architecture](architecture.md), [retrieval methodology](retrieval-and-ranking.md), and
[evidence contract](evidence-and-dossiers.md).

RAGdoll 2.0 presents this workflow through a fullscreen, conversation-first interface. Read the
[terminal experience and v1 migration guide](terminal-experience.md) before using or extending the
interactive surface.
