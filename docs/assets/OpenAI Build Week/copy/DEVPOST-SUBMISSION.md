# Devpost submission copy

Official rules rechecked on 2026-07-18: https://openai.devpost.com/rules

## Project overview

**Project name**

RAGdoll

**Elevator pitch**

RAGdoll turns ambiguous research questions into auditable literature dossiers—with human-approved
search and passage-level citations.

**Thumbnail**

Upload `../gallery/01-ragdoll-cover.png`.

## Project details

### Inspiration

Research assistants can produce a polished answer while hiding how they searched, what they
actually read, and which decisions belonged to the researcher. That is especially dangerous in
scholarly work, where a plausible sentence is not a substitute for a reproducible search or a
supported claim.

I built RAGdoll to keep the receipts. It treats literature research as a workspace rather than a
one-shot prompt: the researcher defines the scope, approves the search plan, curates the papers,
consents before full-text acquisition, and can inspect the exact passage behind every generated
claim.

### What it does

RAGdoll turns an ambiguous research question into an explainable, cited literature dossier from the
terminal. It asks only the clarification questions that affect the search, creates an editable
brief and query plan, and waits for approval before contacting OpenAlex or arXiv. It canonicalizes
metadata with Crossref, groups duplicate versions, exposes ranking components and rationales, and
lets the researcher decide which papers enter the evidence workflow.

Full-text acquisition is a second approval boundary. RAGdoll indexes available open PDFs locally,
labels abstract fallbacks, produces a checkpointed seven-section dossier, answers questions only
from indexed evidence, and resolves every accepted citation to the supplied passage, evidence
level, source, and page locator. Exports include Markdown, BibTeX, JSON, provenance, and cited
evidence.

It never scrapes Google Scholar, bypasses paywalls, or says a paper was read when only metadata or
an abstract was available.

### How I built it

The cloud reasoning boundary uses the OpenAI Responses API with Pydantic structured outputs for
adaptive clarification, research briefs, plans, explainable reranking, cited synthesis, and grounded
answers. The configured GPT-5.6 roles are `gpt-5.6-luna` for fast interaction and
`gpt-5.6-terra` for quality-sensitive synthesis. Every model response crosses domain validation
before it can affect application state.

The rest of the workflow stays behind narrow deterministic adapters. OpenAlex and arXiv provide
discovery, Crossref canonicalizes DOI metadata, reciprocal-rank fusion combines query results,
SQLite persists exact provenance and an FTS5 evidence index, and Textual powers the fullscreen
keyboard-first interface. PDFs are treated as untrusted input and parsed in an isolated,
resource-bounded worker. Canonical fingerprints bind approvals and derived outputs to the exact
plan, staged collection, evidence, model, and endpoint.

Codex was my primary engineering collaborator. It accelerated repository analysis, implementation,
test generation, security hardening, terminal UX refinement, validation, and reproducible media
production. I made the core product decisions: the model proposes while the researcher approves;
retrieval and file access remain application-owned; changing inputs invalidates stale outputs; and
citation integrity is verified separately from semantic entailment.

### Challenges I ran into

Valid JSON was not enough. Plans needed enforceable source and date constraints, citations needed
to resolve only to passages actually supplied to the model, and changing the paper collection
needed to invalidate stale dossiers and answers.

Full-text acquisition added a second trust boundary. Remote URLs and PDFs are untrusted, so RAGdoll
validates redirects and connected peers, rejects private addresses, caps downloads and page counts,
isolates extraction, and falls back honestly when full text is unavailable.

The terminal also had to remain responsive during model, network, and extraction work without
pretending every remote request can be cancelled. The resulting interface combines focused approval
dialogs, expandable timeline cards, paper curation, completion, history, reduced motion, and clear
activity states.

### Accomplishments that I'm proud of

RAGdoll was created during Build Week and progressed through four concrete milestones in its dated
Git history: the initial research preview, a complete evidence workflow, the fullscreen terminal
experience, and hardened v2.2 research contracts.

A documented local acceptance run discovered 24 candidates, manually staged six papers, acquired
five open PDFs plus one labeled abstract fallback, and indexed 307 page-aware passages. Its dossier
contained 25 cited claims across seven sections. Every citation identifier resolved to evidence
supplied for the corresponding model call, and a manual audit found direct passage support for 23
of the 25 claims. I kept the two failures visible because citation integrity is not automatic
entailment verification.

Judges can run a one-command, no-key offline sample that exercises the real product interface and
inspection paths without rebuilding the workflow or paying for a model.

### What I learned

Useful research agents need more than a strong prompt. Structured outputs need domain validation;
citations need enforceable evidence boundaries; changed inputs must invalidate derived state; and
users need meaningful opportunities to correct the system before expensive or privacy-relevant
actions occur.

Explainability becomes operational when the system preserves the exact query, retrieval hit, score
components, human staging decision, evidence level, and cited passage—not merely a generated
rationale.

### What's next

Next I will complete the blinded three-arm retrieval benchmark and hold the v2.2 release until its
documented quality and provenance gates pass. I also plan to improve semantic citation-support
evaluation and make installation easier without weakening the approval or evidence contracts.

### Provider disclosure

The Responses API adapter, GPT-5.6 model configuration, and structured-output contracts are real and
tested offline at the boundary. The documented acceptance run and submitted video use local Ollama
with `qwen3:4b`; they do not simulate or claim a successful paid GPT-5.6 request. A minimal live
GPT-5.6 request was attempted but blocked by API quota.

## Built with

`codex, gpt-5.6, openai-responses-api, python, pydantic, textual, rich, typer, sqlite, sqlite-fts5, httpx, openalex-api, arxiv-api, crossref-api, pypdf, pytest, mypy, ruff, github-actions`

## Links

- Code repository: https://github.com/almondsun/ragdoll
- Documentation: https://almondsun.github.io/ragdoll/

## Gallery order and captions

1. `01-ragdoll-cover.png` — RAGdoll turns a research question into an explainable, cited literature dossier—from your terminal.
2. `02-real-workspace.png` — A keyboard-first workspace for planning searches, curating papers, inspecting evidence, and reading cited dossiers.
3. `03-auditable-workflow.png` — The model proposes; the researcher approves; RAGdoll preserves every query, source, score, decision, and cited passage.
4. `04-human-control.png` — Separate approvals for search, paper curation, full-text acquisition, and evidence inspection keep researchers in control.
5. `05-passage-evidence.png` — Every cited claim links to the exact supplied passage, evidence level, source, and page locator.
6. `06-system-architecture.png` — Model reasoning stays behind Pydantic contracts; narrow adapters enforce retrieval, permissions, and storage.
7. `07-audited-result.png` — Recorded run: 24 candidates, 6 curated papers, 307 evidence chunks, 7 dossier sections, and 23/25 claims supported.

## Video demo link

Paste the final public `https://www.youtube.com/watch?v=...` URL here after upload.

## Additional information

- Submitter type: **Individual**
- Country of residence: **Colombia**
- Category: **Work & Productivity**
- Repository URL: `https://github.com/almondsun/ragdoll`
- `/feedback` session ID: `019f62bf-b2ae-7111-aef2-57baf2ff8414`

**Project access and judge instructions**

Public repository: https://github.com/almondsun/ragdoll

Fast no-key demo:

`uvx --from git+https://github.com/almondsun/ragdoll ragdoll demo --no-animation`

Then inspect `/plan`, `/papers`, `/sources`, `/dossier`, and `/evidence demo-chunk-1`. The demo is
explicitly labeled as a bundled synthetic sample, makes no model or network calls, and is discarded
on exit. Full setup and Ollama/OpenAI paths are in `JUDGING.md`.

**Plugin or developer-tool installation instructions**

Supported and validated: Linux, Python 3.11+, interactive terminal at least 80×24. macOS uses the
same Python and terminal path but is not part of the current automated test matrix. The `uvx`
command above is the fastest test path. For full local use, clone the repository, run
`uv sync --extra dev --extra docs`, pull `qwen3:4b` with Ollama, and run
`uv run ragdoll --provider ollama`.
