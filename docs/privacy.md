# Privacy and security

RAGdoll stores workspaces locally. API secrets are read from environment variables and are never
persisted or exported. Scholarly queries are sent to OpenAlex and arXiv; DOI lookups are sent to
Crossref. In OpenAI mode, the research brief, small ranking batches, and retrieved evidence passages
used for synthesis or Q&A are sent to OpenAI. Ollama mode keeps model inference local, but scholarly
search and approved open-PDF downloads still contact public services.

RAGdoll previews evidence availability and requires confirmation before downloading. It accepts only
unauthenticated HTTPS PDF candidates, rejects non-public resolved addresses and unsafe redirects,
verifies the connected peer address, caps each response at 25 MiB, and limits extraction to 200
pages and 45 seconds by default. The PDF worker fails closed when operating-system resource limits
are unavailable and is capped at 768 MiB of address space, 40 CPU seconds, and 32 MiB of extracted
output. Paper content is treated as untrusted data and never executed.

Approved PDFs are cached beneath `.ragdoll/documents/`, which is ignored by Git. `/purge`
deletes cached documents, indexed chunks, dossier sections, and saved answers for the investigation.
Workspace directories are restricted to the current user (`0700`) and databases, cached documents,
and exports to `0600`.
`Ctrl+G` writes only the current prompt draft to a private (`0600`) temporary file and invokes the
configured editor directly without a shell. The file is deleted when the editor exits and prompts
larger than 1 MiB are rejected.
RAGdoll does not bypass paywalls, perform OCR, scrape Google Scholar, deserialize checkpoints, or run
commands proposed by papers. Exports include evidence levels and stable chunk citations.
