# Retrieval and ranking

OpenAlex is the broad discovery index. arXiv adds current preprints, and Crossref enriches DOI
metadata. Exact DOI and arXiv identities take precedence over conservative title/author grouping.

RAGdoll merges query rankings with reciprocal-rank fusion, then sends at most 50 candidate titles
and abstracts to the configured model. The model grades topical relevance, criteria fit, axis
coverage, evidence availability, and confidence. Final scoring weights are 55% relevance, 25%
criteria fit, and 20% normalized reciprocal rank. Citation counts are metadata, not truth signals.

Auto-staging covers every investigation axis where a qualifying candidate exists, then fills the
remaining requested slots by score. Every decision remains reversible.
