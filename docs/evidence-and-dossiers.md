# Evidence and dossiers

RAGdoll separates paper curation from paper acquisition. `/dossier` first previews the evidence
level available for up to six staged papers. Nothing is downloaded until the user confirms the
preview. Declining leaves the curated collection unchanged.

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
overlap. SQLite FTS5 retrieves a small set of passages for each fixed dossier section and each `/ask`
question. A generated claim is accepted only when all of its cited chunk IDs were supplied to that
model call. Use `/evidence CHUNK_ID` to inspect the exact passage.

This is citation integrity, not automatic entailment verification. The model can still summarize a
passage poorly, and the bounded corpus can omit decisive papers. Treat the dossier as an auditable
research aid and verify important claims against the cited source.

## Dossier lifecycle

The seven sections are executive summary, landscape and taxonomy, cross-paper comparison,
chronological development, agreements and disagreements, evidence limitations, and open questions.
Each section is checkpointed as it completes, so an interrupted build can resume. Use
`/dossier refresh SECTION` to regenerate one section, `/sources` to review acquisition provenance,
and `/purge-evidence` to delete the local evidence cache and derived dossier state.

`/export` writes the reading list as Markdown, BibTeX, and JSON and, when present, the dossier as
Markdown and JSON. The JSON dossier embeds the cited chunks needed to audit it.
