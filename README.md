<div align="center">
  <img src="docs/assets/ragdoll-mascot.svg" alt="RAGdoll minimalist research rag doll" width="160">
  <h1>RAGdoll</h1>
  <p><strong>Turn a research question into an explainable, cited literature dossier—from your terminal.</strong></p>
  <p>Adaptive scoping, editable search plans, transparent ranking, local evidence, and auditable claims.</p>

  [![CI](https://github.com/almondsun/ragdoll/actions/workflows/ci.yml/badge.svg)](https://github.com/almondsun/ragdoll/actions/workflows/ci.yml)
  [![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-2aa198.svg)](https://almondsun.github.io/ragdoll/)
  [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-172a3a.svg)](pyproject.toml)
  [![License: MIT](https://img.shields.io/badge/license-MIT-b87333.svg)](LICENSE)
</div>

RAGdoll is an agentic research workspace for SOTA acceleration. It begins with an ambiguous goal,
asks the pivotal questions that change the investigation, proposes an editable literature-search
plan, and waits for approval before searching. It then discovers, deduplicates, reranks, and stages
a diverse collection of scholarly papers with visible reasons and provenance. With a second,
explicit approval, it downloads available open PDFs, builds a local page-aware evidence index, and
produces a claim-level cited research dossier that can be questioned from the same terminal.

## The interaction

```text
$ ragdoll --topic "I want to understand video generation models"

What are you trying to get from this investigation?

  1. Build a technical understanding
  2. Find the current state of the art
  3. Identify a feasible research direction
  4. Enter my own answer

Select [1-4]:
```

RAGdoll asks at most six adaptive questions. The model supplies exactly three proposed answers;
the terminal owns the fourth custom-answer option. The resulting brief and query plan are shown for
editing and explicit approval before any scholarly API is contacted.

After discovery:

```text
ragdoll> /staged
ragdoll> /inspect 3
ragdoll> /unstage 3
ragdoll> /stage 8
ragdoll> /dossier
ragdoll> /ask Which evaluation limitations recur across these papers?
ragdoll> /evidence chunk-...
ragdoll> /export
```

## Install

```bash
git clone https://github.com/almondsun/ragdoll.git
cd ragdoll
uv sync --extra dev --extra docs
```

Choose a provider:

```bash
export OPENAI_API_KEY=...
uv run ragdoll

# or, fully local model inference with Ollama
ollama pull qwen3:4b
uv run ragdoll --provider ollama
```

OpenAI uses the Responses API. The default fast and quality models are configurable through
`RAGDOLL_OPENAI_FAST_MODEL` and `RAGDOLL_OPENAI_QUALITY_MODEL`. Ollama defaults to `qwen3:4b` and
can be changed with `RAGDOLL_OLLAMA_MODEL`.

## What is explainable

- The original prompt and every clarification answer
- Every plan revision and explicit approval boundary
- Exact source queries and retrieval timestamps
- DOI/arXiv/title-based version grouping and deduplication
- Reciprocal-rank, relevance, and criteria-fit score components
- Why each paper was staged and every later human override
- Whether each claim came from full text or an abstract fallback, including page/chunk locators
- The exact bounded evidence used for every dossier claim and grounded answer

OpenAlex provides broad scholarly discovery, Crossref canonicalizes DOI metadata, and arXiv enriches
preprint records. Coverage varies by field, language, venue, and date; a RAGdoll collection is a
reproducible search result, not the literature itself.

## Development

```bash
uv run make check
```

Normal CI is offline: provider and scholarly-source behavior is tested through strict contracts and
recorded fixtures. Live smoke tests require the corresponding API secret or local runtime.

Read the [architecture](docs/architecture.md), [planning contract](docs/planning-contract.md),
[ranking methodology](docs/retrieval-and-ranking.md),
[evidence and dossier contract](docs/evidence-and-dossiers.md), and
[privacy model](docs/privacy.md) before extending the workflow.

## Status

`v1.0.0` completes the first end-to-end product contract: clarify, approve, discover, curate,
approve evidence acquisition, synthesize, inspect citations, ask bounded questions, and export.
RAGdoll does not bypass paywalls, perform OCR, claim exhaustive coverage, prove novelty, or replace
expert review. Research-gap validation and autonomous experiment design remain outside v1.
