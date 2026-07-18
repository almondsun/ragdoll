# OpenAI Build Week

RAGdoll was built during the July 2026 OpenAI Build Week submission period as a Work & Productivity
project: an explainable terminal workspace that turns a fuzzy research interest into a curated,
cited literature dossier.

[![Watch the RAGdoll OpenAI Build Week demo](assets/OpenAI%20Build%20Week/video/youtube-thumbnail.png)](https://www.youtube.com/watch?v=aytzIq-5S5k)

[Watch the 2:37 demo](https://www.youtube.com/watch?v=aytzIq-5S5k){ .md-button .md-button--primary }
[View the Devpost submission](https://devpost.com/software/ragdoll-xfwzms){ .md-button }
[Inspect the source](https://github.com/almondsun/ragdoll){ .md-button }

## Test it without a key

```bash
uvx --from git+https://github.com/almondsun/ragdoll ragdoll demo --no-animation
```

This launches the real Textual product with a bundled synthetic investigation. It makes no model or
scholarly-source request and discards the temporary workspace on exit. Open `/plan`, `/papers`,
`/sources`, `/dossier`, and `/evidence demo-chunk-1` to follow the audit trail.

## What the recorded run proves

The submission video uses real captures from a saved acceptance investigation: 24 discovered
candidates, six human-curated papers, five open full-text documents, one labeled abstract fallback,
307 page-aware evidence chunks, and a seven-section dossier. All 25 citation identifiers resolved;
23 of 25 claims had direct passage support in the manual semantic audit.

![Recorded RAGdoll acceptance results](assets/OpenAI%20Build%20Week/gallery/07-audited-result.png)

## How Codex and OpenAI fit

Codex was the primary engineering collaborator for repository analysis, implementation, tests,
security hardening, terminal UX refinement, validation, and reproducible media production. Human
product decisions remained explicit: the model proposes while the researcher approves; retrieval
and persistence are application-owned; changed inputs invalidate stale outputs; and citation
integrity is audited separately from entailment.

RAGdoll's cloud adapter uses the OpenAI Responses API and Pydantic structured-output contracts. The
configured fast and quality roles are `gpt-5.6-luna` and `gpt-5.6-terra`. This follows OpenAI's
[official Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs),
and the adapter is contract-tested with recorded fixtures.

!!! warning "Provider provenance"
    The documented acceptance run and submitted video use local Ollama with `qwen3:4b`; they do not
    simulate or claim a successful paid GPT-5.6 request. A minimal live OpenAI request was attempted
    and blocked by API quota. Preserving that distinction is part of RAGdoll's product contract.

## Submission trail

The dated Git history preserves the progression from the initial research preview (`a799ab3`),
through the evidence workflow (`e38a08e`) and fullscreen terminal (`379d1ee`), to hardened v2.2
research contracts (`23e8692`). The public repository also contains the final gallery, video,
captions, narration, and reproducible production frames in the
[submission archive](https://github.com/almondsun/ragdoll/tree/main/docs/assets/OpenAI%20Build%20Week).

- [Judge guide](https://github.com/almondsun/ragdoll/blob/main/JUDGING.md)
- [Acceptance reference run](v1-reference-run.md)
- [Architecture and trust boundaries](architecture.md)
- [Evidence and citation contract](evidence-and-dossiers.md)
