# Planning contract

RAGdoll asks one question at a time. A question is allowed only when its answer can change search
queries, filters, ranking, or output. The model returns exactly three distinct proposed answers and
the client appends a fourth custom-answer option. Previously answered dimensions cannot be repeated.

The interview stops when the request is sufficiently scoped or after six questions. It produces a
durable research brief, followed by an editable plan containing investigation axes, inclusion and
exclusion criteria, query families, sources, and ranking priorities. Search is an explicit approved
transition, not an inferred permission.
