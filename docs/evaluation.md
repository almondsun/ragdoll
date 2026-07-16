# Evaluation

The checked-in 12-topic evaluation set spans computing, medicine, biology, physics, social science,
and the humanities. Its live collector captures three arms under one environment record:

1. raw OpenAlex search using the topic prompt;
2. model-planned queries without clarification;
3. the complete workflow using a fixed checked-in benchmark clarification derived from each topic's
   declared axes.

Every capture records exact papers, retrieval hits, queries, warnings, latency, provider-call counts,
RAGdoll/Python versions, commit, model, and topic checksum. Capturing is deliberately live and is
never a CI test. The collector atomically checkpoints after every arm and resumes an existing output
only when the complete sealed environment matches. A capture requires a clean worktree, records the
model digest/identity and endpoint, and refuses to mix commits, versions, models, Python runtimes, or
topic files. Planned and full-workflow arms score only the requested staged collection:

```bash
uv run python evals/collect.py --provider ollama --output evals/results/v2.2-capture.json
uv run python evals/run.py evals/results/v2.2-capture.json \
  --prepare evals/results/v2.2-judgments.json
```

The worksheet unions candidates across arms and omits arm membership. The maintainer must fill every
0–4 relevance label and covered-axis list, then set `adjudicated_by` and `adjudicated_at`. Only after
that frozen adjudication may scoring run:

```bash
uv run python evals/run.py evals/results/v2.2-capture.json \
  --judgments evals/results/v2.2-judgments.json \
  --output evals/results/v2.2-report.json
```

The report compares recall@20, nDCG@15, investigation-axis coverage, residual duplicate rate,
source/date compliance, identifier auditability, latency, and provider usage. Relevance judgments
are versioned evidence rather than hidden labels, and a worksheet checksum prevents scoring a
different capture.

The v1 evidence acceptance path additionally checks consent, full-text fallback behavior, migration,
claim citation integrity, resumable section synthesis, explicit insufficient-evidence answers, and
Markdown/JSON dossier exports. Citation integrity means every identifier resolves to a supplied
passage; semantic support still requires human auditing and is never presented as automated proof.

The v2.2 release target is mean recall@20 ≥ 0.75, mean nDCG@15 ≥ 0.70, mean axis coverage ≥ 90%,
residual duplicates below 1%, 100% source/date compliance, and no structurally unauditable
identifiers in the full-workflow arm. Source-specific identifier shapes and their association with
the normalized paper are checked; this is a provenance-integrity gate, not independent verification
against the publishers. The scorer exits nonzero when any gate fails. No v2.2 tag or
package may be published until a signed report passes every gate.
