# Evaluation

The checked-in evaluation set spans computing, medicine, biology, physics, social science, and the
humanities. It compares raw OpenAlex search, planned queries without clarification, and the complete
RAGdoll workflow using recall@20, nDCG@15, investigation-axis coverage, duplicate rate, latency, and
provider usage. Human relevance judgments remain versioned evidence rather than hidden labels.

The release target is recall@20 ≥ 0.75, nDCG@15 ≥ 0.70, axis coverage ≥ 90%, residual duplicates
below 1%, and no fabricated identifiers. Live benchmark results require network and a configured
provider and are reported separately from deterministic CI.
