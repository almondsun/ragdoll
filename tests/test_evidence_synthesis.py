from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ragdoll.config import Settings, load_settings
from ragdoll.domain import (
    DocumentStatus,
    EvidenceChunk,
    EvidenceDocument,
    EvidenceLevel,
    FullTextCandidate,
    GroundedClaim,
    ResearchDossier,
)
from ragdoll.evidence import (
    EvidenceError,
    EvidenceService,
    FullTextFetcher,
    _chunks,
    _resolve,
    _write_cache,
)
from ragdoll.export import export_dossier, render_answer
from ragdoll.pdf_worker import extract as worker_extract
from ragdoll.pdf_worker import main as worker_main
from ragdoll.providers import FakeProvider, ProviderError
from ragdoll.service import ResearchService
from ragdoll.storage import SCHEMA_VERSION, Workspace
from ragdoll.synthesis import DraftAnswer, DraftSection, Synthesizer


def public_resolver(hostname: str) -> list[str]:
    del hostname
    return ["93.184.216.34"]


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetcher_enforces_https_public_hosts_size_and_pdf_signature() -> None:
    pdf = b"%PDF-1.4\nfixture"
    fetcher = FullTextFetcher(
        Settings(fulltext_max_bytes=100),
        client(lambda request: httpx.Response(200, content=pdf)),
        public_resolver,
    )
    assert fetcher.fetch("https://papers.example/paper.pdf")[0] == pdf
    with pytest.raises(EvidenceError, match="HTTPS"):
        fetcher.fetch("http://papers.example/paper.pdf")
    private = FullTextFetcher(
        Settings(),
        client(lambda request: httpx.Response(200, content=pdf)),
        lambda host: ["127.0.0.1"],
    )
    with pytest.raises(EvidenceError, match="non-public"):
        private.fetch("https://papers.example/paper.pdf")
    oversized = FullTextFetcher(
        Settings(fulltext_max_bytes=4),
        client(lambda request: httpx.Response(200, content=pdf)),
        public_resolver,
    )
    with pytest.raises(EvidenceError, match="byte limit"):
        oversized.fetch("https://papers.example/paper.pdf")
    invalid = FullTextFetcher(
        Settings(),
        client(lambda request: httpx.Response(200, content=b"html")),
        public_resolver,
    )
    with pytest.raises(EvidenceError, match="not a PDF"):
        invalid.fetch("https://papers.example/paper.pdf")


def test_redirect_destination_is_revalidated() -> None:
    fetcher = FullTextFetcher(
        Settings(),
        client(lambda request: httpx.Response(302, headers={"location": "https://private.test/x"})),
        lambda host: ["127.0.0.1"] if host == "private.test" else ["93.184.216.34"],
    )
    with pytest.raises(EvidenceError, match="non-public"):
        fetcher.fetch("https://public.test/x")


def test_fetcher_rejects_bad_redirects_resolution_and_transport_errors() -> None:
    missing = FullTextFetcher(
        Settings(), client(lambda request: httpx.Response(302)), public_resolver
    )
    with pytest.raises(EvidenceError, match="omitted"):
        missing.fetch("https://papers.example/x")

    looping = FullTextFetcher(
        Settings(),
        client(lambda request: httpx.Response(302, headers={"location": "/again"})),
        public_resolver,
    )
    with pytest.raises(EvidenceError, match="redirect limit"):
        looping.fetch("https://papers.example/x")

    for resolver, message in (
        (lambda host: [], "no addresses"),
        (lambda host: ["invalid"], "invalid address"),
    ):
        with pytest.raises(EvidenceError, match=message):
            FullTextFetcher(Settings(), resolver=resolver).fetch("https://papers.example/x")

    def failed_resolution(host: str) -> list[str]:
        raise OSError(host)

    with pytest.raises(EvidenceError, match="could not be resolved"):
        FullTextFetcher(Settings(), resolver=failed_resolution).fetch("https://papers.example/x")
    failing = FullTextFetcher(
        Settings(), client(lambda request: httpx.Response(503)), public_resolver
    )
    with pytest.raises(EvidenceError, match="request failed"):
        failing.fetch("https://papers.example/x")


def test_default_resolver_normalizes_socket_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ragdoll.evidence.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert _resolve("papers.example") == ["93.184.216.34"]


def test_fetcher_validates_the_actual_connected_peer() -> None:
    class Stream:
        def __init__(self, address: str) -> None:
            self.address = address

        def get_extra_info(self, name: str):
            assert name == "server_addr"
            return (self.address, 443)

    response = lambda address: httpx.Response(  # noqa: E731
        200,
        content=b"%PDF-fixture",
        extensions={"network_stream": Stream(address)},
    )
    private = FullTextFetcher(
        Settings(), client(lambda request: response("127.0.0.1")), public_resolver
    )
    private.require_peer_validation = True
    with pytest.raises(EvidenceError, match="reached a non-public"):
        private.fetch("https://papers.example/x")
    missing = FullTextFetcher(
        Settings(), client(lambda request: httpx.Response(200, content=b"%PDF-x")), public_resolver
    )
    missing.require_peer_validation = True
    with pytest.raises(EvidenceError, match="peer address"):
        missing.fetch("https://papers.example/x")


def test_workspace_migrates_v1_schema(tmp_path: Path) -> None:
    directory = tmp_path / ".ragdoll"
    directory.mkdir()
    connection = sqlite3.connect(directory / "ragdoll.db")
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE investigations (
            id TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            investigation_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        """
    )
    connection.commit()
    connection.close()
    Workspace(tmp_path).initialize()
    with closing(sqlite3.connect(directory / "ragdoll.db")) as connection:
        assert (
            connection.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        )
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert {"evidence_documents", "evidence_chunks", "dossiers"} <= tables


def evidence_records(
    investigation_id: str = "abc123", paper_id: str = "paper-1"
) -> tuple[EvidenceDocument, EvidenceChunk]:
    document = EvidenceDocument(
        id="doc-1",
        investigation_id=investigation_id,
        paper_id=paper_id,
        source="fixture",
        evidence_level=EvidenceLevel.ABSTRACT,
        status=DocumentStatus.FALLBACK,
    )
    chunk = EvidenceChunk(
        id="chunk-1",
        investigation_id=investigation_id,
        paper_id=paper_id,
        document_id=document.id,
        locator="abstract",
        evidence_level=EvidenceLevel.ABSTRACT,
        text="Video diffusion models generate temporally coherent frames and improve coherence.",
        sha256="a" * 64,
    )
    return document, chunk


def test_workspace_indexes_isolates_exports_and_purges(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    assert stat.S_IMODE(workspace.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(workspace.path.stat().st_mode) == 0o600
    document, chunk = evidence_records(investigation.id)
    workspace.save_document(document, [chunk])
    assert workspace.search_chunks(investigation.id, "temporally coherent") == [chunk]
    second_document = document.model_copy(update={"id": "doc-2", "paper_id": "paper-2"})
    second_chunk = chunk.model_copy(
        update={"id": "chunk-2", "document_id": "doc-2", "paper_id": "paper-2"}
    )
    workspace.save_document(second_document, [second_chunk])
    diverse = workspace.search_chunks(
        investigation.id, "temporally coherent", limit=2, per_paper_limit=1
    )
    assert {item.paper_id for item in diverse} == {"paper-1", "paper-2"}
    assert workspace.search_chunks(
        investigation.id,
        "temporally coherent",
        paper_ids={"paper-2"},
    ) == [second_chunk]
    assert workspace.search_chunks("other", "temporally coherent") == []
    dossier = ResearchDossier(
        title="Dossier",
        evidence_summary="1 abstract",
        sections=[
            {
                "title": "Summary",
                "claims": [{"text": "Coherence is addressed.", "chunk_ids": [chunk.id]}],
            }
        ],
    )
    workspace.save_dossier(investigation.id, dossier)
    assert workspace.load_dossier(investigation.id) == dossier
    markdown = export_dossier(
        dossier, investigation, {chunk.id: chunk}, tmp_path / "dossier.md", "markdown"
    )
    assert "abstract" in markdown.read_text(encoding="utf-8")
    workspace.purge_evidence(investigation.id)
    assert workspace.list_documents(investigation.id) == []
    assert workspace.load_dossier(investigation.id) is None


def test_purge_propagates_cache_failures_before_deleting_state(
    tmp_path: Path, investigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id)
    workspace.save_document(document, [chunk])
    cache = workspace.directory / "documents" / investigation.id
    cache.mkdir(parents=True)
    (cache / "paper.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(
        "ragdoll.storage.shutil.rmtree", lambda path: (_ for _ in ()).throw(OSError("denied"))
    )
    with pytest.raises(OSError, match="denied"):
        workspace.purge_evidence(investigation.id)
    assert workspace.document_for(investigation.id, document.paper_id) == document

    monkeypatch.undo()
    target = tmp_path / "target"
    target.mkdir()
    for child in cache.iterdir():
        child.unlink()
    cache.rmdir()
    cache.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError, match="symlinked"):
        workspace.purge_evidence(investigation.id)


def test_purge_refuses_a_symlinked_documents_ancestor(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id)
    workspace.save_document(document, [chunk])
    external = tmp_path / "external"
    cache = external / investigation.id
    cache.mkdir(parents=True)
    protected = cache / "paper.pdf"
    protected.write_bytes(b"pdf")
    documents = workspace.directory / "documents"
    documents.symlink_to(external, target_is_directory=True)

    with pytest.raises(OSError, match="documents directory"):
        workspace.purge_evidence(investigation.id)

    assert protected.exists()
    assert workspace.document_for(investigation.id, document.paper_id) == document


def make_text_pdf(path: Path) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Video diffusion improves motion.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)
    return path.read_bytes()


def test_evidence_service_extracts_pdf_in_worker(tmp_path: Path, investigation, papers) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    content = make_text_pdf(tmp_path / "fixture.pdf")

    class Fetcher:
        def fetch(self, url: str) -> tuple[bytes, str]:
            return content, url

    candidate = FullTextCandidate(url="https://papers.example/test.pdf", source="fixture")
    paper = papers[0].model_copy(update={"fulltext_candidates": [candidate]})
    staged = investigation.model_copy(
        update={"papers": [investigation.papers[0].model_copy(update={"paper": paper})]}
    )
    workspace.save(staged)
    service = EvidenceService(tmp_path, Settings(), workspace, cast(Any, Fetcher()))
    documents, warnings = service.acquire(staged)
    assert warnings == []
    assert documents[0].evidence_level == EvidenceLevel.FULL_TEXT
    chunks = workspace.search_chunks(staged.id, "improves motion")
    assert chunks and chunks[0].locator == "page 1"
    assert Path(workspace.directory / documents[0].relative_path).exists()


def test_evidence_falls_back_to_abstract(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    service = EvidenceService(tmp_path, Settings(), workspace)
    documents, warnings = service.acquire(investigation)
    assert warnings == []
    assert documents[0].evidence_level == EvidenceLevel.ABSTRACT
    assert workspace.search_chunks(investigation.id, "temporally coherent")


def test_evidence_failure_metadata_fallback_and_existing_reuse(
    tmp_path: Path, investigation
) -> None:
    workspace = Workspace(tmp_path)
    candidate = FullTextCandidate(url="https://papers.example/test.pdf", source="fixture")
    paper = investigation.papers[0].paper.model_copy(
        update={"abstract": None, "fulltext_candidates": [candidate]}
    )
    staged = investigation.model_copy(
        update={"papers": [investigation.papers[0].model_copy(update={"paper": paper})]}
    )
    workspace.save(staged)

    class FailingFetcher:
        def fetch(self, url: str) -> tuple[bytes, str]:
            raise EvidenceError(url)

    service = EvidenceService(tmp_path, Settings(), workspace, cast(Any, FailingFetcher()))
    documents, warnings = service.acquire(staged)
    assert documents[0].status == DocumentStatus.FAILED
    assert warnings and "fixture" in warnings[0]

    abstract_paper = paper.model_copy(update={"abstract": "Useful fallback evidence."})
    staged = staged.model_copy(
        update={"papers": [staged.papers[0].model_copy(update={"paper": abstract_paper})]}
    )
    documents, warnings = service.acquire(staged)
    assert documents[0].evidence_level == EvidenceLevel.ABSTRACT
    assert warnings
    reused, _ = service.acquire(staged)
    assert reused == documents


def test_empty_pdf_text_is_removed_before_abstract_fallback(
    tmp_path: Path, investigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    candidate = FullTextCandidate(url="https://papers.example/test.pdf", source="fixture")
    paper = investigation.papers[0].paper.model_copy(update={"fulltext_candidates": [candidate]})
    staged = investigation.model_copy(
        update={"papers": [investigation.papers[0].model_copy(update={"paper": paper})]}
    )
    workspace.save(staged)

    class Fetcher:
        def fetch(self, url: str) -> tuple[bytes, str]:
            return b"%PDF-empty", url

    service = EvidenceService(tmp_path, Settings(), workspace, cast(Any, Fetcher()))
    monkeypatch.setattr(service, "_extract", lambda path, digest: [(1, "")])
    documents, warnings = service.acquire(staged)
    assert documents[0].evidence_level == EvidenceLevel.ABSTRACT
    assert warnings and "no extractable text" in warnings[0]
    assert not list((workspace.directory / "documents" / investigation.id).glob("*.pdf"))


def test_extractor_failures_chunking_and_cache_guards(
    tmp_path: Path, investigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = EvidenceService(tmp_path, Settings(), Workspace(tmp_path))
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fixture")

    class Process:
        def __init__(self, returncode: int = 0, stderr: bytes = b"", timeout: bool = False):
            self.returncode = returncode
            self.stderr = BytesIO(stderr)
            self.timeout = timeout
            self.killed = False

        def wait(self, timeout=None):
            if self.timeout and not self.killed:
                raise subprocess.TimeoutExpired("worker", timeout)
            return self.returncode

        def kill(self):
            self.killed = True

    monkeypatch.setattr(
        "ragdoll.evidence.subprocess.Popen", lambda *args, **kwargs: Process(timeout=True)
    )
    with pytest.raises(EvidenceError, match="timed out"):
        service._extract(pdf, "a" * 64)

    monkeypatch.setattr(
        "ragdoll.evidence.subprocess.Popen",
        lambda *args, **kwargs: Process(1, b"bad pdf"),
    )
    with pytest.raises(EvidenceError, match="bad pdf"):
        service._extract(pdf, "b" * 64)

    monkeypatch.setattr("ragdoll.evidence.subprocess.Popen", lambda *args, **kwargs: Process(0))
    with pytest.raises(EvidenceError, match="invalid output"):
        service._extract(pdf, "c" * 64)

    document, _ = evidence_records(investigation.id)
    assert _chunks(document, "page 1", "") == []
    split = _chunks(document, "page 1", "abcdefgh", size=5, overlap=2)
    assert len(split) == 2 and split[1].locator.endswith("part 2")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_cache(workspace / "ok.pdf", b"pdf", workspace)
    assert (workspace / "ok.pdf").read_bytes() == b"pdf"
    with pytest.raises(EvidenceError, match="escapes"):
        _write_cache(tmp_path / "outside" / "bad.pdf", b"pdf", workspace)


def test_pdf_worker_entrypoint_and_page_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source)
    output = tmp_path / "pages.json"
    worker_extract(source, output, 1)
    assert '"page": 1' in output.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="page limit"):
        worker_extract(source, output, 0)
    with pytest.raises(ValueError, match="output byte limit"):
        worker_extract(source, output, 1, max_output_bytes=1)
    descriptor = os.open(tmp_path / "fd-output.json", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        worker_extract(source, None, 1, output_fd=descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert b'"page": 1' in os.read(descriptor, 100_000)
    finally:
        os.close(descriptor)
    monkeypatch.setattr("ragdoll.pdf_worker._apply_resource_limits", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pdf_worker",
            str(source),
            str(output),
            "--max-pages",
            "1",
            "--max-memory-mib",
            "768",
            "--max-cpu-seconds",
            "40",
            "--max-output-bytes",
            "100000",
        ],
    )
    worker_main()
    assert output.exists()


def test_synthesis_checkpoints_validates_citations_and_answers(
    tmp_path: Path, investigation
) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id, investigation.papers[0].paper.id)
    workspace.save_document(document, [chunk])
    section = DraftSection(
        claims=[GroundedClaim(text="Video diffusion addresses coherence.", chunk_ids=[chunk.id])]
    )
    question_section = DraftSection(
        claims=[GroundedClaim(text="How should coherence be evaluated?", chunk_ids=[chunk.id])]
    )
    limitation_section = DraftSection(
        claims=[GroundedClaim(text="Evaluation is limited.", chunk_ids=[chunk.id])]
    )
    synthesizer = Synthesizer(
        FakeProvider([section] * 5 + [limitation_section, question_section]), workspace
    )
    dossier = synthesizer.generate(investigation)
    assert len(dossier.sections) == 7
    assert workspace.load_dossier(investigation.id) == dossier

    invalid = DraftAnswer(
        claims=[GroundedClaim(text="Unsupported.", chunk_ids=["chunk-fabricated"])],
        explanation="Grounded response.",
    )
    valid = DraftAnswer(
        claims=[GroundedClaim(text="Coherence is discussed.", chunk_ids=[chunk.id])],
        explanation="Grounded response.",
    )
    answer = Synthesizer(FakeProvider([invalid, valid]), workspace).answer(
        investigation, "What improves coherence?"
    )
    assert answer.claims[0].chunk_ids == [chunk.id]
    assert answer.explanation == "Answer limited to the cited indexed passages."
    assert "abstract" in render_answer(answer, {chunk.id: chunk})
    with pytest.raises(ProviderError, match="invalid evidence citations"):
        Synthesizer(FakeProvider([invalid, invalid]), workspace).answer(
            investigation, "What improves coherence?"
        )


def test_synthesis_reports_insufficient_evidence(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    answer = Synthesizer(FakeProvider([]), workspace).answer(
        investigation, "What does the corpus say about underwater robotics?"
    )
    assert answer.insufficient_evidence
    assert answer.claims == []


def test_empty_draft_answer_is_normalized_to_insufficiency(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id, investigation.papers[0].paper.id)
    workspace.save_document(document, [chunk])

    answer = Synthesizer(
        FakeProvider([DraftAnswer(explanation="No supporting claim found.")]), workspace
    ).answer(investigation, "What is unsupported?")

    assert answer.insufficient_evidence
    assert answer.claims == []


def test_open_question_section_is_repaired(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id, investigation.papers[0].paper.id)
    workspace.save_document(document, [chunk])
    factual = DraftSection(
        claims=[GroundedClaim(text="Coherence is discussed.", chunk_ids=[chunk.id])]
    )
    question = DraftSection(
        claims=[GroundedClaim(text="How should coherence be evaluated?", chunk_ids=[chunk.id])]
    )
    limitation = DraftSection(
        claims=[GroundedClaim(text="Evaluation is limited.", chunk_ids=[chunk.id])]
    )
    dossier = Synthesizer(
        FakeProvider([factual] * 5 + [limitation, factual, question]), workspace
    ).generate(investigation)
    assert dossier.sections[-1].claims[0].text.endswith("?")


def test_service_builds_abstract_dossier_end_to_end(tmp_path: Path, investigation) -> None:
    section = DraftSection(claims=[])
    service = ResearchService(tmp_path, Settings(), FakeProvider([section] * 7))
    service.workspace.save(investigation)
    service.approve_evidence(investigation)
    updated, dossier, warnings = service.build_dossier(investigation)
    assert warnings == []
    assert updated.dossier_status == "ready"
    assert len(dossier.sections) == 7
    assert service.workspace.load_dossier(investigation.id) == dossier


def test_dossier_resumes_from_section_checkpoint(tmp_path: Path, investigation) -> None:
    workspace = Workspace(tmp_path)
    workspace.save(investigation)
    document, chunk = evidence_records(investigation.id, investigation.papers[0].paper.id)
    workspace.save_document(document, [chunk])
    section = DraftSection(
        claims=[GroundedClaim(text="Coherence is discussed.", chunk_ids=[chunk.id])]
    )
    with pytest.raises(ProviderError, match="queue is empty"):
        Synthesizer(FakeProvider([section]), workspace).generate(investigation)
    checkpoint = workspace.load_dossier(investigation.id)
    assert checkpoint is not None and len(checkpoint.sections) == 1
    question_section = DraftSection(
        claims=[GroundedClaim(text="How should coherence be evaluated?", chunk_ids=[chunk.id])]
    )
    limitation_section = DraftSection(
        claims=[GroundedClaim(text="Evaluation is limited.", chunk_ids=[chunk.id])]
    )
    completed = Synthesizer(
        FakeProvider([section] * 4 + [limitation_section, question_section]), workspace
    ).generate(investigation)
    assert len(completed.sections) == 7


def test_numeric_environment_configuration_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAGDOLL_DOSSIER_PAPER_LIMIT", "4")
    assert load_settings(tmp_path).dossier_paper_limit == 4
