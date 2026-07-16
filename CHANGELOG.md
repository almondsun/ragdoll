# Changelog

## 1.0.0 — 2026-07-15

- Added consent-gated acquisition of openly available PDFs with bounded, isolated extraction and
  abstract fallback.
- Added a local page-aware FTS5 evidence index and transactional schema-v1-to-v2 migration.
- Added checkpointed seven-section dossiers with claim-level passage citations and targeted section
  refresh.
- Added grounded `/ask`, evidence/source inspection, evidence purging, and dossier Markdown/JSON
  exports.
- Hardened evidence handling with connected-peer SSRF checks, bounded PDF worker resources, private
  workspace permissions, and fail-closed cache deletion.
- Made `qwen3:4b` the default Ollama model and validated the end-to-end local-provider path.

## 0.1.0 — 2026-07-15

- Initial research-preview release of adaptive planning, scholarly discovery, explainable ranking,
  diverse staging, persistent workspaces, and reproducible exports.
