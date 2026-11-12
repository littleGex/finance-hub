import sqlite3

import pytest

from app import config, db

# The schema as shipped in the first release (commit 9a62643), before pots/recurring/transfers.
V0_SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    bank TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    opening_balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    booked_on TEXT NOT NULL,
    amount REAL NOT NULL,
    counterparty TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    dedup_key TEXT NOT NULL UNIQUE
);
"""


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_init_migrates_v0_database(db_path):
    raw = sqlite3.connect(db_path)
    raw.executescript(V0_SCHEMA)
    raw.execute("INSERT INTO accounts(name, bank) VALUES ('Giro', 'sparkasse')")
    raw.execute("INSERT INTO transactions(account_id, booked_on, amount, dedup_key) VALUES (1, '2026-11-01', -5, 'k')")
    raw.commit()
    raw.close()

    db.init()

    with db.session() as conn:
        assert {"counterparty_iban", "is_transfer"} <= _cols(conn, "transactions")
        assert "iban" in _cols(conn, "accounts")
        assert {"anchor_balance", "anchor_date"} <= _cols(conn, "pots")
        assert {"frequency", "due_day", "start_month", "to_pot_id", "active"} <= _cols(conn, "recurring")
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT is_transfer FROM transactions").fetchone()[0] == 0


def test_init_is_idempotent(db_path):
    db.init()
    db.init()


def test_iban_unique_but_nulls_allowed(db_path):
    db.init()
    with db.session() as conn:
        conn.execute("INSERT INTO accounts(name, bank) VALUES ('A', 'x')")
        conn.execute("INSERT INTO accounts(name, bank) VALUES ('B', 'x')")      # both NULL: fine
        conn.execute("INSERT INTO accounts(name, bank, iban) VALUES ('C', 'x', 'DE1')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO accounts(name, bank, iban) VALUES ('D', 'x', 'DE1')")


def test_pot_names_unique_per_account(db_path):
    db.init()
    with db.session() as conn:
        conn.execute("INSERT INTO accounts(name, bank) VALUES ('A', 'x')")
        conn.execute("INSERT INTO accounts(name, bank) VALUES ('B', 'x')")
        conn.execute("INSERT INTO pots(account_id, name, anchor_balance, anchor_date) VALUES (1, 'Kids', 0, '2026-11-12')")
        conn.execute("INSERT INTO pots(account_id, name, anchor_balance, anchor_date) VALUES (2, 'Kids', 0, '2026-11-12')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO pots(account_id, name, anchor_balance, anchor_date) VALUES (1, 'Kids', 0, '2026-11-12')")
