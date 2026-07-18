# Published YouTube metadata

https://www.youtube.com/watch?v=aytzIq-5S5k

## Title

RAGdoll — Explainable Scholarly Research with Codex | OpenAI Build Week

## Description

RAGdoll turns an ambiguous research question into an explainable, cited literature dossier while
keeping search approval, paper curation, evidence acquisition, and claim inspection in the
researcher's hands.

This video resumes the documented local acceptance investigation completed with Ollama and
`qwen3:4b`; it does not simulate a live OpenAI API request. RAGdoll includes an OpenAI Responses API
adapter configured for GPT-5.6 and protected by Pydantic output contracts, but that paid integration
is not represented as successfully executed in this recording.

Codex supported repository analysis, implementation, validation, security hardening, and media
production. The recorded run contains 24 candidates, six curated papers, five open full-text
documents, one abstract fallback, 307 page-aware chunks, seven dossier sections, and 25 cited
claims.

Code: https://github.com/almondsun/ragdoll

No-key judge demo:
`uvx --from git+https://github.com/almondsun/ragdoll ragdoll demo --no-animation`

Documentation: https://almondsun.github.io/ragdoll/

OpenAI Build Week category: Work & Productivity
