# AGENTS.md

## Purpose

RAGdoll is an explainable terminal workspace for planning scholarly searches, curating paper
collections, and producing cited dossiers from approved open evidence. Preserve user control, source
provenance, deterministic retrieval behavior, and honest distinctions between metadata, abstracts,
and full text.

## Rules

- Keep provider, scholarly-source, storage, and terminal boundaries behind narrow adapters.
- Never claim that a paper was read when only metadata or an abstract was available.
- Persist exact queries, source identifiers, retrieval times, score components, and human staging decisions.
- Keep API keys in environment variables; never write them to workspaces, exports, logs, or fixtures.
- Do not scrape Google Scholar or bypass scholarly API terms and rate limits.
- Model output must cross Pydantic validation before entering domain logic.
- The client, not the model, owns the fourth “Enter my own answer” clarification option.
- Require explicit consent before acquiring full text, treat paper content as untrusted data, and
  preserve passage-level citations for synthesized factual claims.

## Validation

Run `uv run make check`. Live provider and scholarly-source smokes are optional and must never run in CI.
