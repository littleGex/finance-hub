"""SQLite storage."""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    bank TEXT NOT NULL,              -- sparkasse | ing | bos | other
    currency TEXT NOT NULL DEFAULT 'EUR',   -- unused: everything is EUR
    opening_balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    booked_on TEXT NOT NULL,         -- ISO date
    amount REAL NOT NULL,            -- EUR, negative = outgoing
    counterparty TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(booked_on);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    rows_total INTEGER NOT NULL,
    rows_new INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payslips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    period TEXT,                     -- YYYY-MM when detected
    gross REAL,
    net REAL,
    stored_path TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    name TEXT NOT NULL,
    anchor_balance REAL NOT NULL DEFAULT 0,   -- balance at the END of anchor_date
    anchor_date TEXT NOT NULL,                -- ISO date
    UNIQUE (account_id, name)
);
CREATE TABLE IF NOT EXISTS recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    amount REAL NOT NULL,                     -- EUR, > 0, paid out of from_account_id
    from_account_id INTEGER NOT NULL REFERENCES accounts(id),
    frequency TEXT NOT NULL,                  -- monthly | quarterly | yearly
    due_day INTEGER NOT NULL,                 -- 1-31, clamped to month end
    start_month TEXT NOT NULL,                -- YYYY-MM
    to_account_id INTEGER REFERENCES accounts(id),   -- set => transfer, else bill
    to_pot_id INTEGER REFERENCES pots(id),
    active INTEGER NOT NULL DEFAULT 1
);
"""

# Columns added after the first release; applied to existing databases on startup.
ADDED_COLUMNS = (
    ("accounts", "iban", "TEXT"),                                   # normalised, no spaces
    ("transactions", "counterparty_iban", "TEXT"),
    ("transactions", "is_transfer", "INTEGER NOT NULL DEFAULT 0"),
)


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in ADDED_COLUMNS:
            _add_column(conn, table, column, decl)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_iban ON accounts(iban) WHERE iban IS NOT NULL")
