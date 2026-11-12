from datetime import date

import pytest

from tests.conftest import make_account

IA = "DE89370400440532013000"
IB = "DE02120300000000202051"


@pytest.fixture()
def accts(client, monkeypatch):
    from app import plan
    monkeypatch.setattr(plan, "today", lambda: date(2026, 11, 12))
    giro = make_account(client, "Giro", "sparkasse")
    spar = make_account(client, "Sparkonto", "sparkasse")
    ing = make_account(client, "ING", "ing")
    return client, giro, spar, ing


def pot(c, account_id, name="Children", balance=0):
    r = c.post(f"/api/accounts/{account_id}/pots", json={"name": name, "balance": balance})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def item(c, **kw):
    body = {"name": "Rent", "amount": 1150, "from_account_id": 1, "frequency": "monthly",
            "due_day": 1, "start_month": "2026-01"} | kw
    return c.post("/api/recurring", json=body)


def summary_pots(c, account_id):
    return {p["name"]: p["balance"] for a in c.get("/api/summary").json()["accounts"]
            if a["id"] == account_id for p in a["pots"]}


# ---- IBAN ----

def test_iban_normalised(accts):
    c, giro, *_ = accts
    r = c.patch(f"/api/accounts/{giro}", json={"iban": "de89 3704 0044 0532 0130 00"})
    assert r.status_code == 200 and r.json()["iban"] == IA


def test_iban_duplicate_conflicts(accts):
    c, giro, spar, _ = accts
    c.patch(f"/api/accounts/{giro}", json={"iban": IA})
    assert c.patch(f"/api/accounts/{spar}", json={"iban": IA}).status_code == 409


def test_iban_garbage_rejected(accts):
    c, giro, *_ = accts
    assert c.patch(f"/api/accounts/{giro}", json={"iban": "abc"}).status_code == 400


def test_iban_null_clears(accts):
    c, giro, *_ = accts
    c.patch(f"/api/accounts/{giro}", json={"iban": IA})
    assert c.patch(f"/api/accounts/{giro}", json={"iban": None}).json()["iban"] is None


def test_iban_unknown_account_404(accts):
    c, *_ = accts
    assert c.patch("/api/accounts/999", json={"iban": IA}).status_code == 404


# ---- pots ----

def test_pot_create_and_duplicate_name(accts):
    c, _, spar, _ = accts
    pot(c, spar, "Children", 300)
    assert summary_pots(c, spar) == {"Children": 300.0}
    assert c.post(f"/api/accounts/{spar}/pots", json={"name": "Children"}).status_code == 409


def test_pot_patch_balance_and_name(accts):
    c, _, spar, _ = accts
    p = pot(c, spar, "Kids", 100)
    assert c.patch(f"/api/pots/{p}", json={"balance": 250, "name": "Children"}).status_code == 200
    assert summary_pots(c, spar) == {"Children": 250.0}


def test_pot_delete_refused_when_referenced(accts):
    c, giro, spar, _ = accts
    p = pot(c, spar)
    item(c, name="Kids monthly", amount=100, from_account_id=giro, to_account_id=spar, to_pot_id=p)
    item(c, name="Kids birthday", amount=50, from_account_id=giro, frequency="yearly",
         to_account_id=spar, to_pot_id=p)
    r = c.delete(f"/api/pots/{p}")
    assert r.status_code == 409
    assert "Kids monthly" in r.json()["detail"] and "Kids birthday" in r.json()["detail"]


def test_pot_delete_unreferenced(accts):
    c, _, spar, _ = accts
    p = pot(c, spar)
    assert c.delete(f"/api/pots/{p}").status_code == 204
    assert summary_pots(c, spar) == {}


# ---- recurring: validation ----

@pytest.mark.parametrize("override", [
    {"amount": 0}, {"amount": -5}, {"due_day": 0}, {"due_day": 32}, {"frequency": "weekly"},
    {"start_month": "2026-13"}, {"start_month": "Nov 2026"}, {"name": "  "},
])
def test_recurring_invalid_fields(accts, override):
    c, giro, *_ = accts
    assert item(c, from_account_id=giro, **override).status_code in (400, 422)


def test_transfer_to_same_account_rejected(accts):
    c, giro, *_ = accts
    assert item(c, from_account_id=giro, to_account_id=giro).status_code == 400


def test_pot_without_target_account_rejected(accts):
    c, giro, spar, _ = accts
    p = pot(c, spar)
    assert item(c, from_account_id=giro, to_pot_id=p).status_code == 400


def test_pot_of_other_account_rejected(accts):
    c, giro, spar, ing = accts
    p = pot(c, spar)
    assert item(c, from_account_id=giro, to_account_id=ing, to_pot_id=p).status_code == 400


@pytest.mark.parametrize("override", [{"from_account_id": 999}, {"to_account_id": 999}])
def test_unknown_accounts_404(accts, override):
    c, giro, *_ = accts
    assert item(c, **({"from_account_id": giro} | override)).status_code == 404


def test_unknown_pot_404(accts):
    c, giro, spar, _ = accts
    assert item(c, from_account_id=giro, to_account_id=spar, to_pot_id=999).status_code == 404


def test_patch_target_account_with_stale_pot_rejected(accts):
    c, giro, spar, ing = accts
    p = pot(c, spar)
    i = item(c, from_account_id=giro, to_account_id=spar, to_pot_id=p).json()["id"]
    assert c.patch(f"/api/recurring/{i}", json={"to_account_id": ing}).status_code == 400


# ---- recurring: CRUD and pot re-anchoring ----

def test_create_list_with_next_due(accts):
    c, giro, *_ = accts
    r = item(c, from_account_id=giro, name="Car insurance", amount=600, frequency="yearly",
             due_day=15, start_month="2026-03")
    assert r.status_code == 201
    rows = c.get("/api/recurring").json()
    assert rows[0]["name"] == "Car insurance" and rows[0]["next_due"] == "2027-03-15"


def test_patch_amount_keeps_pot_balance_today(accts, monkeypatch):
    c, giro, spar, _ = accts
    from app import plan
    monkeypatch.setattr(plan, "today", lambda: date(2026, 9, 15))
    p = pot(c, spar, "Children", 500)                       # anchored 2026-09-15
    i = item(c, name="Kids", amount=100, from_account_id=giro, to_account_id=spar, to_pot_id=p).json()["id"]
    monkeypatch.setattr(plan, "today", lambda: date(2026, 11, 12))
    assert summary_pots(c, spar) == {"Children": 700.0}
    assert c.patch(f"/api/recurring/{i}", json={"amount": 200}).status_code == 200
    assert summary_pots(c, spar) == {"Children": 700.0}     # past contributions kept
    monkeypatch.setattr(plan, "today", lambda: date(2026, 12, 1))
    assert summary_pots(c, spar) == {"Children": 900.0}     # new amount from next due date


def test_pause_and_delete_keep_pot_balance(accts, monkeypatch):
    c, giro, spar, _ = accts
    from app import plan
    monkeypatch.setattr(plan, "today", lambda: date(2026, 9, 15))
    p = pot(c, spar, "Children", 500)
    i = item(c, name="Kids", amount=100, from_account_id=giro, to_account_id=spar, to_pot_id=p).json()["id"]
    monkeypatch.setattr(plan, "today", lambda: date(2026, 11, 12))
    assert c.patch(f"/api/recurring/{i}", json={"active": False}).status_code == 200
    monkeypatch.setattr(plan, "today", lambda: date(2027, 2, 1))
    assert summary_pots(c, spar) == {"Children": 700.0}
    assert c.delete(f"/api/recurring/{i}").status_code == 204
    assert summary_pots(c, spar) == {"Children": 700.0}
    assert c.get("/api/recurring").json() == []


def test_unknown_recurring_404(accts):
    c, *_ = accts
    assert c.patch("/api/recurring/999", json={"amount": 5}).status_code == 404
    assert c.delete("/api/recurring/999").status_code == 404


def test_iban_change_reruns_transfer_detection(accts):
    c, giro, spar, _ = accts
    from app import db
    with db.session() as conn:
        conn.execute("""INSERT INTO transactions(account_id, booked_on, amount, counterparty_iban, dedup_key)
                        VALUES (?, '2026-11-05', -100, ?, 'k1')""", (giro, IB))
    c.patch(f"/api/accounts/{spar}", json={"iban": "de02 1203 0000 0000 2020 51"})
    assert c.get("/api/transactions").json()[0]["is_transfer"] == 1


def test_creating_item_does_not_backfill_pot(accts, monkeypatch):
    c, giro, spar, _ = accts
    from app import plan
    monkeypatch.setattr(plan, "today", lambda: date(2026, 9, 15))
    p = pot(c, spar, "Children", 500)
    monkeypatch.setattr(plan, "today", lambda: date(2026, 11, 12))
    item(c, name="Kids", amount=100, from_account_id=giro, start_month="2026-01", to_account_id=spar, to_pot_id=p)
    assert summary_pots(c, spar) == {"Children": 500.0}     # no retroactive Oct/Nov contributions
