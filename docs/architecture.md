# Architecture

```mermaid
flowchart LR
  A[Research interest] --> B[Adaptive clarification]
  B --> C[Research brief]
  C --> D[Editable plan]
  D -->|approval| E[OpenAlex + arXiv]
  E --> F[Normalize + deduplicate]
  F --> G[Reciprocal-rank fusion]
  G --> H[Explainable model rerank]
  H --> I[Diverse staged corpus]
  I --> J[Markdown + BibTeX + JSON]
```

Domain objects are independent from terminals, providers, scholarly APIs, and SQLite. Pydantic
validation protects every model boundary. The service layer owns orchestration and persistence;
model providers never write files or call scholarly sources directly.

Workspaces live in `.ragdoll/`. SQLite stores restorable investigation snapshots plus an append-only
event trail. The export layer reads only validated domain state.
