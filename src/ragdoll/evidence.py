"""Consent-gated acquisition, isolated extraction, and local evidence chunking."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .config import Settings
from .domain import (
    DocumentStatus,
    EvidenceChunk,
    EvidenceDocument,
    EvidenceLevel,
    Investigation,
    Paper,
)
from .storage import Workspace


class EvidenceError(RuntimeError):
    """Evidence could not be acquired or extracted safely."""


Resolver = Callable[[str], list[str]]


def _resolve(hostname: str) -> list[str]:
    return list(
        {str(item[4][0]) for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
    )


class FullTextFetcher:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        resolver: Resolver = _resolve,
    ) -> None:
        self.settings = settings
        self.require_peer_validation = client is None
        self.client = client or httpx.Client(
            timeout=settings.fulltext_timeout_seconds,
            trust_env=False,
        )
        self.resolver = resolver

    def fetch(self, url: str) -> tuple[bytes, str]:
        current = url
        for _ in range(4):
            self._validate_url(current)
            try:
                with self.client.stream("GET", current, follow_redirects=False) as response:
                    self._validate_peer(response)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise EvidenceError("full-text redirect omitted its destination")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared and int(declared) > self.settings.fulltext_max_bytes:
                        raise EvidenceError("full text exceeds the configured byte limit")
                    data = bytearray()
                    for block in response.iter_bytes():
                        data.extend(block)
                        if len(data) > self.settings.fulltext_max_bytes:
                            raise EvidenceError("full text exceeds the configured byte limit")
            except (httpx.HTTPError, ValueError) as error:
                raise EvidenceError(f"full-text request failed: {error}") from error
            if not bytes(data).lstrip().startswith(b"%PDF-"):
                raise EvidenceError("full-text response is not a PDF")
            return bytes(data), current
        raise EvidenceError("full-text request exceeded the redirect limit")

    def _validate_peer(self, response: httpx.Response) -> None:
        stream = response.extensions.get("network_stream")
        if stream is None:
            if self.require_peer_validation:
                raise EvidenceError("full-text connection did not expose its peer address")
            return
        try:
            peer = stream.get_extra_info("server_addr")
            address = peer[0] if isinstance(peer, tuple) and peer else None
        except (AttributeError, OSError, TypeError) as error:
            raise EvidenceError("full-text peer address could not be verified") from error
        if not isinstance(address, str):
            raise EvidenceError("full-text connection did not expose its peer address")
        _validate_public_address(address, "full-text connection reached a non-public address")

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise EvidenceError("full-text URLs must be unauthenticated HTTPS URLs")
        try:
            addresses = self.resolver(parsed.hostname)
        except OSError as error:
            raise EvidenceError("full-text hostname could not be resolved") from error
        if not addresses:
            raise EvidenceError("full-text hostname resolved to no addresses")
        for address in addresses:
            _validate_public_address(address, "full-text URL resolves to a non-public address")


class EvidenceService:
    def __init__(
        self,
        root: Path,
        settings: Settings,
        workspace: Workspace,
        fetcher: FullTextFetcher | None = None,
    ) -> None:
        self.root = root
        self.settings = settings
        self.workspace = workspace
        self.fetcher = fetcher or FullTextFetcher(settings)

    def acquire(self, investigation: Investigation) -> tuple[list[EvidenceDocument], list[str]]:
        staged = [item.paper for item in investigation.papers if item.staged]
        staged = staged[: self.settings.dossier_paper_limit]
        documents: list[EvidenceDocument] = []
        warnings: list[str] = []
        for paper in staged:
            existing = self.workspace.document_for(investigation.id, paper.id)
            if existing and existing.status != DocumentStatus.FAILED:
                documents.append(existing)
                continue
            document, chunks, warning = self._acquire_paper(investigation.id, paper)
            self.workspace.save_document(document, chunks)
            documents.append(document)
            if warning:
                warnings.append(warning)
        return documents, warnings

    def _acquire_paper(
        self, investigation_id: str, paper: Paper
    ) -> tuple[EvidenceDocument, list[EvidenceChunk], str | None]:
        errors: list[str] = []
        for candidate in paper.fulltext_candidates:
            try:
                content, final_url = self.fetcher.fetch(candidate.url)
                digest = hashlib.sha256(content).hexdigest()
                relative = Path("documents") / investigation_id / f"{digest}.pdf"
                destination = self.workspace.directory / relative
                _write_cache(destination, content, self.workspace.directory)
                try:
                    pages = self._extract(destination, digest)
                    document = EvidenceDocument(
                        id=_document_id(investigation_id, paper.id, digest),
                        investigation_id=investigation_id,
                        paper_id=paper.id,
                        source_url=final_url,
                        source=candidate.source,
                        license=candidate.license,
                        evidence_level=EvidenceLevel.FULL_TEXT,
                        status=DocumentStatus.AVAILABLE,
                        sha256=digest,
                        media_type="application/pdf",
                        byte_count=len(content),
                        page_count=len(pages),
                        relative_path=str(relative),
                    )
                    chunks = _page_chunks(document, pages)
                    if not chunks:
                        raise EvidenceError("PDF contained no extractable text")
                except EvidenceError:
                    destination.unlink(missing_ok=True)
                    raise
                return document, chunks, None
            except (EvidenceError, OSError) as error:
                errors.append(f"{candidate.source}: {error}")
        if paper.abstract:
            document = _fallback_document(investigation_id, paper, EvidenceLevel.ABSTRACT, errors)
            return document, _abstract_chunks(document, paper.abstract), _warning(paper, errors)
        document = _fallback_document(investigation_id, paper, EvidenceLevel.METADATA, errors)
        return document, [], _warning(paper, errors or ["no abstract or open full text"])

    def _extract(self, path: Path, digest: str) -> list[tuple[int, str]]:
        output = path.with_name(f"{digest}.json")
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("pdf_worker.py")),
            str(path),
            str(output),
            "--max-pages",
            str(self.settings.fulltext_max_pages),
            "--max-memory-mib",
            str(self.settings.extraction_max_memory_mib),
            "--max-cpu-seconds",
            str(self.settings.extraction_max_cpu_seconds),
            "--max-output-bytes",
            str(self.settings.extraction_max_output_bytes),
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.settings.extraction_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise EvidenceError("PDF extraction timed out") from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown"
            raise EvidenceError(f"PDF extraction failed: {detail[:200]}")
        try:
            if output.stat().st_size > self.settings.extraction_max_output_bytes:
                raise EvidenceError("PDF extractor output exceeded the configured byte limit")
            data = json.loads(output.read_text(encoding="utf-8"))
            return [(int(page["page"]), str(page["text"])) for page in data["pages"]]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise EvidenceError("PDF extractor returned invalid output") from error
        finally:
            output.unlink(missing_ok=True)


def _fallback_document(
    investigation_id: str, paper: Paper, level: EvidenceLevel, errors: list[str]
) -> EvidenceDocument:
    digest = hashlib.sha256(f"{investigation_id}:{paper.id}:{level}".encode()).hexdigest()
    return EvidenceDocument(
        id=_document_id(investigation_id, paper.id, digest),
        investigation_id=investigation_id,
        paper_id=paper.id,
        source_url=paper.url,
        source="scholarly metadata",
        evidence_level=level,
        status=DocumentStatus.FALLBACK
        if level == EvidenceLevel.ABSTRACT
        else DocumentStatus.FAILED,
        error="; ".join(errors)[:500] or None,
    )


def _warning(paper: Paper, errors: list[str]) -> str | None:
    if not errors:
        return None
    return f"{paper.title}: {'; '.join(errors)}"


def _page_chunks(document: EvidenceDocument, pages: list[tuple[int, str]]) -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    for page, text in pages:
        chunks.extend(_chunks(document, f"page {page}", text))
    return chunks


def _abstract_chunks(document: EvidenceDocument, abstract: str) -> list[EvidenceChunk]:
    return _chunks(document, "abstract", abstract)


def _chunks(
    document: EvidenceDocument, locator: str, text: str, size: int = 1800, overlap: int = 200
) -> list[EvidenceChunk]:
    clean = " ".join(text.split())
    if not clean:
        return []
    result: list[EvidenceChunk] = []
    start = 0
    part = 1
    while start < len(clean):
        value = clean[start : start + size]
        digest = hashlib.sha256(value.encode()).hexdigest()
        identity = hashlib.sha256(f"{document.id}:{locator}:{part}:{digest}".encode()).hexdigest()
        label = locator if len(clean) <= size else f"{locator}, part {part}"
        result.append(
            EvidenceChunk(
                id=f"chunk-{identity[:24]}",
                investigation_id=document.investigation_id,
                paper_id=document.paper_id,
                document_id=document.id,
                locator=label,
                evidence_level=document.evidence_level,
                text=value,
                sha256=digest,
            )
        )
        if start + size >= len(clean):
            break
        start += size - overlap
        part += 1
    return result


def _document_id(investigation_id: str, paper_id: str, digest: str) -> str:
    identity = hashlib.sha256(f"{investigation_id}:{paper_id}:{digest}".encode()).hexdigest()
    return f"doc-{identity[:24]}"


def _validate_public_address(address: str, message: str) -> None:
    try:
        if not ipaddress.ip_address(address).is_global:
            raise EvidenceError(message)
    except ValueError as error:
        raise EvidenceError("full-text hostname returned an invalid address") from error


def _write_cache(destination: Path, content: bytes, workspace: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.parent.chmod(0o700)
    root = workspace.resolve()
    parent = destination.parent.resolve()
    if not parent.is_relative_to(root):
        raise EvidenceError("document cache path escapes the workspace")
    descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)
        raise
