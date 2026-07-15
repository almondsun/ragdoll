"""Durable, inspectable SQLite workspace state."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .domain import Investigation

SCHEMA_VERSION = 1


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / ".ragdoll"
        self.path = self.directory / "ragdoll.db"

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
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
            elif row[0] != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported workspace schema version {row[0]}")
            connection.commit()

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

    def list(self) -> list[Investigation]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM investigations ORDER BY updated_at DESC"
            ).fetchall()
        return [Investigation.model_validate_json(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection
