# Evidence and dossiers

RAGdoll separates paper curation from paper acquisition. `/dossier` first previews the evidence
level available for up to six staged papers. Nothing is downloaded until the user confirms the
preview. The confirmation names the actual provider, model, endpoint, and whether transport is local
or remote. Declining leaves the curated collection unchanged. Consent is persisted against both that
destination and the exact staged-corpus fingerprint, and is enforced by the service layer.
The approval contract also includes the configured acquisition limit and exact ordered paper IDs
shown in the preview. Cached documents participate only when they match that acquisition contract.

## Acquisition contract

- Prefer declared open-access HTTPS PDF candidates from arXiv or OpenAlex.
- Revalidate every redirect and reject URL authentication, non-HTTPS URLs, and non-public IP
  addresses.
- Verify the actual connected peer remains public after DNS resolution and every redirect.
- Enforce configured response-size, page-count, request-time, extraction-time, memory, CPU, and
  extracted-output limits.
- Parse PDFs in an isolated subprocess and remove failed cache entries.
- Fall back to the indexed abstract when full text is unavailable or extraction fails.
- Preserve the final URL, source, license when known, checksum, evidence level, and page locators.

No OCR, paywall bypass, browser automation, or arbitrary attachment format is attempted.

## Local index and citations

Extracted text is normalized into page-aware chunks of at most 1,800 characters with a 200-character
overlap. SQLite FTS5 retrieves a bounded candidate pool for each fixed dossier section and each
`/ask` question, then applies per-paper diversity and excludes chunks from unstaged papers. A
generated claim is accepted only when all of its cited chunk IDs were supplied to that
model call. Use `/evidence CHUNK_ID` to inspect the exact passage.

This is citation integrity, not automatic entailment verification. The model can still summarize a
passage poorly, and the bounded corpus can omit decisive papers. Treat the dossier as an auditable
research aid and verify important claims against the cited source.

## Dossier lifecycle

The seven sections are executive summary, landscape and taxonomy, cross-paper comparison,
chronological development, agreements and disagreements, evidence limitations, and open questions.
Each section is checkpointed as it completes, so an interrupted build can resume. Use
`/dossier refresh SECTION` to regenerate one section, `/sources` to review acquisition provenance,
and `/purge` to delete the local evidence cache and derived dossier state after confirmation.

Every dossier and grounded answer carries staged-corpus and evidence fingerprints. Changing the
staged collection deletes dossiers and answers immediately and requires new evidence consent; raw
evidence records remain cached but cannot participate until they match the current staged contract.
Legacy schema-v2 derived outputs have no fingerprints and therefore appear stale until rebuilt.

`/export` writes the reading list as Markdown, BibTeX, and JSON and, when present, the dossier as
Markdown and JSON. The JSON dossier embeds the cited chunks needed to audit it.
