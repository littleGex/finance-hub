from app.gamify import monthly_cashflow
from app.transfers import is_plausible_iban, mark_transfers, normalize_iban
from tests.conftest import add_account

IA = "DE89370400440532013000"
IB = "DE02120300000000202051"
_keys = iter(range(10**9))


def tx(conn, account_id, day, amount, iban=None):
    return conn.execute(
        """INSERT INTO transactions(account_id, booked_on, amount, counterparty_iban, dedup_key)
           VALUES (?,?,?,?,?)""",
        (account_id, f"2026-11-{day:02d}", amount, iban, f"k{next(_keys)}"),
    ).lastrowid


def marked(conn):
    return {r[0] for r in conn.execute("SELECT id FROM transactions WHERE is_transfer = 1")}


def test_normalize_iban_strips_spaces_and_uppercases():
    assert normalize_iban("de12 3456 7890 1234 5678 90") == "DE12345678901234567890"


def test_normalize_iban_rejects_non_ibans():
    assert normalize_iban("1234567") is None
    assert normalize_iban("") is None
    assert normalize_iban(None) is None
    assert not is_plausible_iban("abc")


def test_direct_match_and_pairing(conn):
    a = add_account(conn, "Giro", iban=IA)
    b = add_account(conn, "Sparkonto", iban=IB)
    t1 = tx(conn, a, 5, -100, IB)      # direct
    t2 = tx(conn, b, 7, 100)           # paired with t1 (2 days)
    tx(conn, b, 20, 100)               # outside the window
    t4 = tx(conn, a, 6, -50, IB)       # direct
    tx(conn, b, 4, 50)                 # 2 days away: loses to t6
    t6 = tx(conn, b, 6, 50)            # same day: closest wins
    t7 = tx(conn, a, 5, -100, IB)      # direct; its counterpart t2 is already taken
    assert mark_transfers(conn) == 5
    assert marked(conn) == {t1, t2, t4, t6, t7}


def test_removing_iban_unmarks_on_recompute(conn):
    a = add_account(conn, "Giro", iban=IA)
    b = add_account(conn, "Sparkonto", iban=IB)
    tx(conn, a, 5, -100, IB)
    tx(conn, b, 5, 100)
    mark_transfers(conn)
    conn.execute("UPDATE accounts SET iban = NULL WHERE id = ?", (b,))
    assert mark_transfers(conn) == 0
    assert marked(conn) == set()


def test_transfers_excluded_from_cashflow(conn):
    a = add_account(conn, "Giro", iban=IA)
    b = add_account(conn, "Sparkonto", iban=IB)
    tx(conn, a, 1, 3000)               # salary from employer
    tx(conn, a, 5, -300, IB)
    tx(conn, b, 5, 300)
    tx(conn, a, 9, -80)                # groceries
    mark_transfers(conn)
    assert monthly_cashflow(conn)["2026-11"] == {"income": 3000.0, "spend": 80.0}


def test_both_legs_direct_do_not_swallow_same_amount_spend(conn):
    giro = add_account(conn, "Giro", iban=IA)
    spar = add_account(conn, "Sparkonto", iban=IB)
    t1 = tx(conn, giro, 5, -100, IB)       # Giro export names the savings IBAN
    t2 = tx(conn, spar, 5, 100, IA)        # savings export names the Giro IBAN
    t3 = tx(conn, giro, 7, -100)           # unrelated ATM withdrawal, same amount
    mark_transfers(conn)
    assert marked(conn) == {t1, t2}
    assert t3 not in marked(conn)
