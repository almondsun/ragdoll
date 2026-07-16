"""Durable, inspectable SQLite workspace state."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .domain import EvidenceChunk, EvidenceDocument, GroundedAnswer, Investigation, ResearchDossier

SCHEMA_VERSION = 2


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / ".ragdoll"
        self.path = self.directory / "ragdoll.db"
        self._permissions_protected = False

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS investigations (
                    id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    investigation_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(investigation_id) REFERENCES investigations(id)
                );
                """
            )
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
                )
                self._create_evidence_schema(connection)
            elif row[0] == 1:
                self._create_evidence_schema(connection)
                connection.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
            elif row[0] == SCHEMA_VERSION:
                self._create_evidence_schema(connection)
            else:
                raise RuntimeError(f"unsupported workspace schema version {row[0]}")
            connection.commit()
        if not self._permissions_protected:
            self._protect_workspace_files()
            self._permissions_protected = True

    def _create_evidence_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_documents (
                id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE(investigation_id, paper_id),
                FOREIGN KEY(investigation_id) REFERENCES investigations(id)
            );
            CREATE TABLE IF NOT EXISTS evidence_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                investigation_id TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                locator TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES evidence_documents(id) ON DELETE CASCADE,
                FOREIGN KEY(investigation_id) REFERENCES investigations(id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                chunk_id UNINDEXED,
                investigation_id UNINDEXED,
                text,
                tokenize = 'porter unicode61'
            );
            CREATE TABLE IF NOT EXISTS dossiers (
                investigation_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(investigation_id) REFERENCES investigations(id)
            );
            CREATE TABLE IF NOT EXISTS questions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                investigation_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(investigation_id) REFERENCES investigations(id)
            );
            """
        )

    def save(self, investigation: Investigation, event: str = "snapshot") -> None:
        self.initialize()
        payload = investigation.model_dump_json()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO investigations(id, updated_at, payload) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload=excluded.payload""",
                (investigation.id, investigation.updated_at.isoformat(), payload),
            )
            connection.execute(
                "INSERT INTO events(investigation_id, kind, payload) VALUES (?, ?, ?)",
                (investigation.id, event, payload),
            )
            connection.commit()

    def load(self, investigation_id: str) -> Investigation:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM investigations WHERE id = ?", (investigation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(investigation_id)
        return Investigation.model_validate_json(row[0])

    def latest(self) -> Investigation:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM investigations ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise KeyError("no investigations")
        return Investigation.model_validate_json(row[0])

    def list_investigations(self) -> list[Investigation]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM investigations ORDER BY updated_at DESC"
            ).fetchall()
        return [Investigation.model_validate_json(row[0]) for row in rows]

    def save_document(self, document: EvidenceDocument, chunks: list[EvidenceChunk]) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            prior = connection.execute(
                """SELECT id FROM evidence_documents
                WHERE investigation_id = ? AND paper_id = ?""",
                (document.investigation_id, document.paper_id),
            ).fetchone()
            prior_id = prior[0] if prior else document.id
            old_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM evidence_chunks WHERE document_id = ?", (prior_id,)
                )
            ]
            for chunk_id in old_ids:
                connection.execute("DELETE FROM evidence_fts WHERE chunk_id = ?", (chunk_id,))
            connection.execute("DELETE FROM evidence_chunks WHERE document_id = ?", (prior_id,))
            if prior and prior_id != document.id:
                connection.execute("DELETE FROM evidence_documents WHERE id = ?", (prior_id,))
            connection.execute(
                """INSERT INTO evidence_documents(id, investigation_id, paper_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(investigation_id, paper_id) DO UPDATE SET
                    id=excluded.id, payload=excluded.payload""",
                (
                    document.id,
                    document.investigation_id,
                    document.paper_id,
                    document.model_dump_json(),
                ),
            )
            for chunk in chunks:
                connection.execute(
                    """INSERT INTO evidence_chunks(
                        id, document_id, investigation_id, paper_id, locator, payload
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.investigation_id,
                        chunk.paper_id,
                        chunk.locator,
                        chunk.model_dump_json(),
                    ),
                )
                connection.execute(
                    "INSERT INTO evidence_fts(chunk_id, investigation_id, text) VALUES (?, ?, ?)",
                    (chunk.id, chunk.investigation_id, chunk.text),
                )
            connection.commit()

    def document_for(self, investigation_id: str, paper_id: str) -> EvidenceDocument | None:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT payload FROM evidence_documents
                WHERE investigation_id = ? AND paper_id = ?""",
                (investigation_id, paper_id),
            ).fetchone()
        return EvidenceDocument.model_validate_json(row[0]) if row else None

    def list_documents(self, investigation_id: str) -> list[EvidenceDocument]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT payload FROM evidence_documents
                WHERE investigation_id = ? ORDER BY paper_id""",
                (investigation_id,),
            ).fetchall()
        return [EvidenceDocument.model_validate_json(row[0]) for row in rows]

    def search_chunks(
        self,
        investigation_id: str,
        query: str,
        limit: int = 3,
        per_paper_limit: int | None = None,
    ) -> list[EvidenceChunk]:
        self.initialize()
        terms = [term for term in re.findall(r"[A-Za-z0-9]{2,}", query.casefold())][:24]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
        fetch_limit = limit if per_paper_limit is None else limit * 4
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT evidence_chunks.payload
                FROM evidence_fts
                JOIN evidence_chunks ON evidence_chunks.id = evidence_fts.chunk_id
                WHERE evidence_fts MATCH ? AND evidence_fts.investigation_id = ?
                ORDER BY bm25(evidence_fts) LIMIT ?""",
                (expression, investigation_id, fetch_limit),
            ).fetchall()
        chunks = [EvidenceChunk.model_validate_json(row[0]) for row in rows]
        if per_paper_limit is None:
            return chunks
        selected: list[EvidenceChunk] = []
        counts: dict[str, int] = {}
        for chunk in chunks:
            if counts.get(chunk.paper_id, 0) >= per_paper_limit:
                continue
            selected.append(chunk)
            counts[chunk.paper_id] = counts.get(chunk.paper_id, 0) + 1
            if len(selected) == limit:
                break
        return selected

    def chunks(self, chunk_ids: list[str]) -> dict[str, EvidenceChunk]:
        if not chunk_ids:
            return {}
        self.initialize()
        placeholders = ",".join("?" for _ in chunk_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT payload FROM evidence_chunks WHERE id IN ({placeholders})", chunk_ids
            ).fetchall()
        chunks = [EvidenceChunk.model_validate_json(row[0]) for row in rows]
        return {chunk.id: chunk for chunk in chunks}

    def save_dossier(self, investigation_id: str, dossier: ResearchDossier) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO dossiers(investigation_id, updated_at, payload) VALUES (?, ?, ?)
                ON CONFLICT(investigation_id) DO UPDATE SET
                    updated_at=excluded.updated_at, payload=excluded.payload""",
                (investigation_id, datetime.now(UTC).isoformat(), dossier.model_dump_json()),
            )
            connection.commit()

    def load_dossier(self, investigation_id: str) -> ResearchDossier | None:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM dossiers WHERE investigation_id = ?", (investigation_id,)
            ).fetchone()
        return ResearchDossier.model_validate_json(row[0]) if row else None

    def remove_dossier_section(self, investigation_id: str, title: str) -> bool:
        dossier = self.load_dossier(investigation_id)
        if dossier is None:
            return False
        sections = [
            section for section in dossier.sections if section.title.casefold() != title.casefold()
        ]
        if len(sections) == len(dossier.sections) or not sections:
            return False
        self.save_dossier(investigation_id, dossier.model_copy(update={"sections": sections}))
        return True

    def save_answer(self, investigation_id: str, answer: GroundedAnswer) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO questions(investigation_id, occurred_at, payload) VALUES (?, ?, ?)",
                (investigation_id, datetime.now(UTC).isoformat(), answer.model_dump_json()),
            )
            connection.commit()

    def purge_evidence(self, investigation_id: str) -> None:
        self.initialize()
        documents = self.directory / "documents"
        if documents.is_symlink():
            raise OSError("refusing to purge through a symlinked documents directory")
        cache = documents / investigation_id
        if cache.is_symlink():
            raise OSError("refusing to purge a symlinked evidence cache")
        if cache.exists():
            documents_resolved = documents.resolve()
            cache_resolved = cache.resolve()
            if not cache_resolved.is_relative_to(documents_resolved):
                raise OSError("evidence cache path escapes the documents directory")
            shutil.rmtree(cache)
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM evidence_fts WHERE investigation_id = ?", (investigation_id,)
            )
            connection.execute(
                "DELETE FROM dossiers WHERE investigation_id = ?", (investigation_id,)
            )
            connection.execute(
                "DELETE FROM questions WHERE investigation_id = ?", (investigation_id,)
            )
            connection.execute(
                "DELETE FROM evidence_documents WHERE investigation_id = ?", (investigation_id,)
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            self._protect_database_files()
        except Exception:
            connection.close()
            raise
        return connection

    def _protect_workspace_files(self) -> None:
        self._protect_database_files()
        for name in ("documents", "exports"):
            root = self.directory / name
            if not root.exists() or root.is_symlink():
                continue
            for directory, child_directories, files in os.walk(root, followlinks=False):
                current = Path(directory)
                current.chmod(0o700)
                child_directories[:] = [
                    item for item in child_directories if not (current / item).is_symlink()
                ]
                for file in files:
                    path = current / file
                    if not path.is_symlink():
                        path.chmod(0o600)

    def _protect_database_files(self) -> None:
        for path in (
            self.path,
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)
