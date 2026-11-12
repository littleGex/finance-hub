import pytest

from app import config, db


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A migrated, empty database connection (committed on close)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "unit.db")
    db.init()
    c = db.connect()
    yield c
    c.commit()
    c.close()


def add_account(conn, name, bank="sparkasse", iban=None, opening=0.0):
    return conn.execute("INSERT INTO accounts(name, bank, iban, opening_balance) VALUES (?,?,?,?)",
                        (name, bank, iban, opening)).lastrowid


def add_pot(conn, account_id, name, balance, anchor_date):
    return conn.execute("INSERT INTO pots(account_id, name, anchor_balance, anchor_date) VALUES (?,?,?,?)",
                        (account_id, name, balance, anchor_date)).lastrowid


def add_item(conn, name, amount, from_account_id, frequency="monthly", due_day=1, start_month="2026-01",
             to_account_id=None, to_pot_id=None, active=1):
    return conn.execute(
        """INSERT INTO recurring(name, amount, from_account_id, frequency, due_day, start_month,
                                 to_account_id, to_pot_id, active) VALUES (?,?,?,?,?,?,?,?,?)""",
        (name, amount, from_account_id, frequency, due_day, start_month, to_account_id, to_pot_id, active),
    ).lastrowid
