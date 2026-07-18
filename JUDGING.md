# RAGdoll judging guide

RAGdoll is a Python 3.11+ terminal application. Linux is the validated platform; macOS has the same
Python and terminal requirements. Use a terminal of at least `80 x 24` cells.

## Fastest path: offline product demo

This command installs the public repository into an isolated `uvx` environment and opens the real
RAGdoll Textual interface with a bundled synthetic investigation:

```bash
uvx --from git+https://github.com/almondsun/ragdoll ragdoll demo --no-animation
```

No API key, model download, external scholarly request, or persistent workspace is used. The header
and timeline label the investigation as an offline sample. Try:

```text
/plan
/papers
/sources
/dossier
/evidence demo-chunk-1
```

Inference, evidence acquisition, dossier refresh, purge, and grounded Q&A are disabled in this
sample. Paper-selection changes are discarded. Exit with `Ctrl+D` or two empty `Ctrl+C` presses.

## Full local workflow with Ollama

```bash
git clone https://github.com/almondsun/ragdoll.git
cd ragdoll
uv sync --extra dev --extra docs
ollama pull qwen3:4b
uv run ragdoll --provider ollama
```

The application asks for explicit plan approval before scholarly discovery and separate consent
before it downloads available open PDFs or sends evidence passages to the configured model.

## OpenAI provider

```bash
export OPENAI_API_KEY=your_key_here
uv run ragdoll --provider openai
```

The OpenAI adapter uses the Responses API with Pydantic structured outputs. Defaults are
`gpt-5.6-luna` for fast interactions and `gpt-5.6-terra` for quality-sensitive work. Override them
with `RAGDOLL_OPENAI_FAST_MODEL` and `RAGDOLL_OPENAI_QUALITY_MODEL`.

## Validation

```bash
uv run make check
```

Normal validation is offline. Live provider and scholarly-source smokes are optional and never run
in CI. The Build Week acceptance record is documented in
[`docs/v1-reference-run.md`](docs/v1-reference-run.md).
