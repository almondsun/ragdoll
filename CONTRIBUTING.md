# Contributing

Use Python 3.11 or newer and `uv sync --extra dev --extra docs`. Keep changes within the approved
research-workspace scope and run `uv run make check`. New provider or source adapters require offline
contract fixtures, explicit rate-limit behavior, provenance preservation, and privacy documentation.
Changes to acquisition, parsing, indexing, citations, or migrations also require focused failure-path
tests and a security review of their trust boundaries.
