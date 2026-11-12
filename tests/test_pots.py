from datetime import date

import pytest

from app.pots import account_pots, pot_balance, reanchor_pots, set_pot_balance
from tests.conftest import add_account, add_item, add_pot


@pytest.fixture()
def setup(conn):
    giro = add_account(conn, "Giro")
    spar = add_account(conn, "Sparkonto")
    pot = add_pot(conn, spar, "Children", 500.0, "2026-09-15")
    item = add_item(conn, "To children", 100.0, giro, due_day=1, start_month="2026-01",
                    to_account_id=spar, to_pot_id=pot)
    return conn, pot, item, giro, spar


def test_balance_is_anchor_plus_transfers_since(setup):
    conn, pot, *_ = setup
    assert pot_balance(conn, pot, date(2026, 11, 12)) == 700.0   # Oct 1 + Nov 1


def test_set_by_hand_restarts_from_new_anchor(setup):
    conn, pot, *_ = setup
    set_pot_balance(conn, pot, 650.0, date(2026, 11, 12))
    assert pot_balance(conn, pot, date(2026, 11, 12)) == 650.0
    assert pot_balance(conn, pot, date(2026, 12, 1)) == 750.0


def test_anchor_on_due_date_excludes_that_days_item(setup):
    conn, pot, *_ = setup
    set_pot_balance(conn, pot, 650.0, date(2026, 12, 1))
    assert pot_balance(conn, pot, date(2026, 12, 1)) == 650.0


def test_reanchor_then_edit_same_day_no_double_count(setup):
    conn, pot, item, *_ = setup
    set_pot_balance(conn, pot, 650.0, date(2026, 12, 1))
    reanchor_pots(conn, [pot], date(2026, 12, 1))
    conn.execute("UPDATE recurring SET amount = 200 WHERE id = ?", (item,))
    assert pot_balance(conn, pot, date(2026, 12, 1)) == 650.0
    assert pot_balance(conn, pot, date(2027, 1, 1)) == 850.0


def test_reanchor_keeps_past_contributions_when_paused(setup):
    conn, pot, item, *_ = setup
    reanchor_pots(conn, [pot], date(2026, 11, 12))
    conn.execute("UPDATE recurring SET active = 0 WHERE id = ?", (item,))
    assert pot_balance(conn, pot, date(2027, 3, 1)) == 700.0


def test_bill_without_pot_never_affects_pots(setup):
    conn, pot, _, giro, _ = setup
    add_item(conn, "Rent", 1150.0, giro, due_day=1)
    assert pot_balance(conn, pot, date(2026, 11, 12)) == 700.0


def test_reanchor_ignores_none(setup):
    conn, pot, *_ = setup
    reanchor_pots(conn, [None], date(2026, 12, 1))
    assert pot_balance(conn, pot, date(2026, 11, 12)) == 700.0


def test_account_pots_listed_by_name(setup):
    conn, pot, _, _, spar = setup
    add_pot(conn, spar, "Anna", 10.0, "2026-11-12")
    assert account_pots(conn, spar, date(2026, 11, 12)) == [
        {"id": pot + 1, "name": "Anna", "balance": 10.0},
        {"id": pot, "name": "Children", "balance": 700.0},
    ]
