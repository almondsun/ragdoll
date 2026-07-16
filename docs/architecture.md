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
  I --> J{Evidence approval}
  J -->|approved| K[Open PDF acquisition]
  J -->|declined| I
  K --> L[Isolated extraction + local FTS]
  L --> M[Cited dossier + grounded Q&A]
  I --> N[Reading-list exports]
  M --> O[Dossier Markdown + JSON]
```

Domain objects are independent from terminals, providers, scholarly APIs, and SQLite. Pydantic
validation protects every model boundary. The service layer owns orchestration and persistence;
model providers never write files or call scholarly sources directly.

Workspaces live in `.ragdoll/`. SQLite schema v2 stores restorable investigation snapshots, an
append-only event trail, evidence-document provenance, page-aware chunks, an FTS5 index, checkpointed
dossier sections, and question history. Existing schema-v1 workspaces migrate transactionally.

Network acquisition, PDF parsing, model inference, persistence, and terminal rendering remain
separate boundaries. PDF extraction runs in an isolated Python subprocess with byte, page, and time
limits. The export layer reads only validated domain state.
