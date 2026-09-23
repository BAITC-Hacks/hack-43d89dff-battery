"""SQLite persistence for the marketplace MVP."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    contact_name TEXT,
    contact_email TEXT,
    owner_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    contact_email TEXT NOT NULL,
    owner_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(id),
    initial_draft TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '[]',
    task_summary TEXT,
    card_json TEXT,
    evaluation_json TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('awaiting_answers', 'card_ready', 'confirmed', 'published')
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    confirmed_at TEXT,
    published_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_business ON tasks(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, published_at DESC);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    team_id TEXT NOT NULL REFERENCES teams(id),
    message TEXT NOT NULL,
    approach TEXT NOT NULL,
    estimated_timeline TEXT,
    portfolio_links_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'submitted' CHECK (
        status IN ('submitted', 'accepted', 'rejected', 'withdrawn')
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    decided_at TEXT,
    UNIQUE(task_id, team_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_accepted_proposal_per_task
ON proposals(task_id) WHERE status = 'accepted';
CREATE INDEX IF NOT EXISTS idx_proposals_task ON proposals(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_team ON proposals(team_id, created_at DESC);
"""


SCHEMA_VERSION = 1

# Version zero is the original token-owned marketplace schema above. Execute
# migrations statement by statement inside one IMMEDIATE transaction: SQLite's
# executescript() would otherwise commit that transaction before applying DDL.
MIGRATIONS = {
    1: (
        """CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('business', 'student')),
            business_id TEXT UNIQUE REFERENCES businesses(id),
            team_id TEXT UNIQUE REFERENCES teams(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            CHECK (
                (role = 'business' AND business_id IS NOT NULL AND team_id IS NULL)
                OR (role = 'student' AND team_id IS NOT NULL AND business_id IS NULL)
            )
        )""",
        """CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
        )""",
        "CREATE INDEX idx_sessions_expiry ON sessions(expires_at)",
        "CREATE INDEX idx_sessions_account ON sessions(account_id)",
    ),
}


class Database:
    """Small connection factory with safe per-operation transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def initialize(self) -> None:
        path = Path(self.path)
        if self.path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("This database requires a newer application version.")
            # Check compatibility before any DDL. Keep baseline creation and
            # all pending migrations in this same rollback-safe transaction.
            statement = ""
            for line in SCHEMA.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise RuntimeError("The database schema contains an incomplete statement.")
            for next_version in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[next_version]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {next_version}")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if self.path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Yield a read connection and always close it after the operation."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
