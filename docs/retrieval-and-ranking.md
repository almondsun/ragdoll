# Retrieval and ranking

OpenAlex and arXiv are selectable discovery indexes; Crossref is a separately disclosed metadata
enricher and never causes an undeclared discovery search. Approved date bounds are sent to each
discovery provider and then enforced again after normalization. When a bounded search returns a
record without a usable publication date, RAGdoll excludes it and reports a warning.

Each retrieval is persisted as an indivisible `{source, source_id, query, rank, retrieved_at}` hit.
RRF is computed from those hits, so its derivation remains reconstructible after merging. Legacy
v2 records remain readable but are marked as having incomplete provenance rather than receiving
invented source/query associations.

Deduplication builds an alias graph across normalized DOI, versionless arXiv ID, and exact normalized
title plus first author. This links common preprint/published pairs while retaining every retrieval
hit and available identifier.

RAGdoll merges query rankings with reciprocal-rank fusion, shortlists at most 24 candidates, then
sends batches of at most three titles and truncated abstracts to the configured model. The model
grades topical relevance, criteria fit, axis
coverage, evidence availability, and confidence. Final scoring weights are 55% relevance, 25%
criteria fit, and 20% normalized reciprocal rank. Citation counts are metadata, not truth signals.

Auto-staging covers investigation axes where a qualifying candidate exists, then fills remaining
slots by score, and never exceeds the approved paper count. Every decision remains reversible.

Ranking is an aid to human curation, not a quality or truth score. A staged set may be edited before
any evidence is acquired, and dossier synthesis uses at most the first six staged papers by default.
