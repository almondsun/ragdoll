# Retrieval and ranking

OpenAlex is the broad discovery index. arXiv adds current preprints, and Crossref enriches DOI
metadata. Exact DOI and arXiv identities take precedence over conservative title/author grouping.

RAGdoll merges query rankings with reciprocal-rank fusion, shortlists at most 24 candidates, then
sends batches of at most three titles and truncated abstracts to the configured model. The model
grades topical relevance, criteria fit, axis
coverage, evidence availability, and confidence. Final scoring weights are 55% relevance, 25%
criteria fit, and 20% normalized reciprocal rank. Citation counts are metadata, not truth signals.

Auto-staging covers every investigation axis where a qualifying candidate exists, then fills the
remaining requested slots by score. Every decision remains reversible.

Ranking is an aid to human curation, not a quality or truth score. A staged set may be edited before
any evidence is acquired, and dossier synthesis uses at most the first six staged papers by default.
