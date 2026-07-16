# Planning contract

RAGdoll asks one question at a time. A question is allowed only when its answer can change search
queries, filters, ranking, or output. The model returns exactly three distinct proposed answers and
the client appends a fourth custom-answer option. Previously answered dimensions cannot be repeated.

The interview stops when the request is sufficiently scoped or after six questions. It produces a
durable research brief, followed by an editable plan containing investigation axes, inclusion and
exclusion criteria, query families, discovery sources, separately disclosed metadata enrichers,
and ranking priorities. The review shows date bounds and both source classes. Approval persists the
SHA-256 fingerprint of the brief and plan; any revision creates a different contract and requires a
new approval. The service enforces this invariant for every caller, so search is an explicit approved
transition rather than a TUI convention.
