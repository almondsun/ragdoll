# Privacy and security

RAGdoll stores workspaces locally. API secrets are read from environment variables and are never
persisted or exported. Scholarly queries are sent to OpenAlex and arXiv; DOI lookups are sent to
Crossref. In OpenAI mode, the research brief and up to 50 candidate titles and abstracts are sent to
OpenAI. Ollama mode keeps model inference local, but scholarly search still uses public APIs.

RAGdoll does not download or execute paper attachments, deserialize checkpoints, scrape Google
Scholar, or run commands proposed by papers. Exports state whether an abstract was available.
