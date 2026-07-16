# v1 reference run

This is the release acceptance run for RAGdoll 1.0.0. It is a functional and grounding audit, not
a retrieval-quality benchmark or a claim that the resulting collection is representative of the
whole video-generation literature.

## Environment and workflow

- Date: 2026-07-15
- Topic: `I want to understand the current state of video generation models`
- Provider: Ollama 0.32.0 with `qwen3:4b`, CPU inference
- Investigation: `d47140cc0bd5`
- Discovery result: 24 reranked candidates; six manually staged papers
- Evidence result: five open PDFs and one abstract fallback; 307 page-aware chunks
- Output: seven ordered dossier sections, reading-list exports, dossier Markdown/JSON, and two saved
  grounded answers

The operator completed adaptive clarification, edited and approved the plan, reviewed the ranked
collection, manually selected six papers, previewed the evidence sources, and separately approved
open-PDF acquisition. The generated dossier was then inspected, selected sections were refreshed,
one supported question was answered with a passage citation, and an unsupported “best model” question
returned explicit insufficient evidence.

The successful local commands were:

```bash
RAGDOLL_PROVIDER=ollama uv run ragdoll --topic \
  "I want to understand the current state of video generation models"
RAGDOLL_PROVIDER=ollama uv run ragdoll resume
RAGDOLL_PROVIDER=ollama uv run ragdoll doctor
```

Interactive acceptance covered `/stage`, `/unstage`, `/dossier`, `/dossier refresh`, `/sources`,
`/ask`, `/evidence`, `/export`, resume after interruption, and the acquisition consent boundary.

## Citation audit

The final dossier contains 25 factual or question claims. Every citation identifier resolves to a
chunk supplied to the corresponding model call. A manual claim-by-passage audit found 23 of 25
claims directly supported (92%). The two failures were retained in this record:

1. A comparison claim said MA ViS outperformed three named baselines on several metrics, while the
   cited passage established the comparison setup but did not contain those results.
2. A chronological claim described control limitations as belonging to “early” models, while the
   cited passage described the limitation without supporting that temporal qualifier.

This meets the preregistered 90% semantic-support target but demonstrates why citation integrity is
not entailment verification. Important dossier claims still require human inspection with
`/evidence CHUNK_ID` and the source paper.

## Findings and release interpretation

The end-to-end contract works locally: consent is explicit, evidence provenance is inspectable,
full-text failures fall back safely, sections checkpoint and resume, unsupported Q&A fails closed,
and exports are self-auditing. Live use also exposed and led to fixes for repeated clarification
dimensions, oversized reranking calls, Ollama reasoning latency, search resume behavior, malformed
insufficiency state, single-source evidence concentration, section-order drift, and mislabeled
limitations.

Retrieval quality in this run was uneven. The original generated query plan used overly complex
Boolean-like strings and the 24-paper shortlist included several off-topic results. The operator had
to curate the corpus manually, and the final dossier leaned heavily on a survey and MA ViS. v1 now
instructs the planner to emit short source-neutral query phrases, but that improvement was not used
to rerun this frozen reference investigation. Accordingly, this run accepts the product workflow
and grounding boundary only; it does not satisfy or replace the separate live retrieval benchmark
described in [Evaluation](evaluation.md).
