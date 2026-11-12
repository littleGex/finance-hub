"""API for account IBANs, pots and regular payments."""
from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from . import db, plan, pots, transfers

router = APIRouter(prefix="/api")

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class IbanIn(BaseModel):
    iban: str | None = None


class PotIn(BaseModel):
    name: str
    balance: float = 0.0


class PotPatch(BaseModel):
    name: str | None = None
    balance: float | None = None


class RecurringIn(BaseModel):
    name: str
    amount: float
    from_account_id: int
    frequency: str
    due_day: int
    start_month: str
    to_account_id: int | None = None
    to_pot_id: int | None = None
    active: bool = True


class RecurringPatch(BaseModel):
    name: str | None = None
    amount: float | None = None
    from_account_id: int | None = None
    frequency: str | None = None
    due_day: int | None = None
    start_month: str | None = None
    to_account_id: int | None = None
    to_pot_id: int | None = None
    active: bool | None = None


FIELDS = tuple(RecurringIn.model_fields)


def _get(conn, table: str, row_id: int, what: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"No such {what}")
    return row


# ---------- accounts ----------

@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: IbanIn):
    with db.session() as conn:
        _get(conn, "accounts", account_id, "account")
        iban = None
        if body.iban and body.iban.strip():
            iban = transfers.normalize_iban(body.iban)
            if iban is None:
                raise HTTPException(400, "That doesn't look like an IBAN")
        try:
            conn.execute("UPDATE accounts SET iban = ? WHERE id = ?", (iban, account_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Another account already has this IBAN")
        transfers.mark_transfers(conn)
        return {"id": account_id, "iban": iban}


# ---------- pots ----------

def _pot_out(conn, pot_id: int) -> dict:
    row = _get(conn, "pots", pot_id, "pot")
    return {"id": pot_id, "account_id": row["account_id"], "name": row["name"],
            "balance": pots.pot_balance(conn, pot_id, plan.today())}


def _pot_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(400, "Pot name is required")
    return name


@router.post("/accounts/{account_id}/pots", status_code=201)
def create_pot(account_id: int, body: PotIn):
    with db.session() as conn:
        _get(conn, "accounts", account_id, "account")
        try:
            cur = conn.execute(
                "INSERT INTO pots(account_id, name, anchor_balance, anchor_date) VALUES (?,?,?,?)",
                (account_id, _pot_name(body.name), body.balance, plan.today().isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "This account already has a pot with that name")
        return _pot_out(conn, cur.lastrowid)


@router.patch("/pots/{pot_id}")
def update_pot(pot_id: int, body: PotPatch):
    with db.session() as conn:
        _get(conn, "pots", pot_id, "pot")
        if body.name is not None:
            try:
                conn.execute("UPDATE pots SET name = ? WHERE id = ?", (_pot_name(body.name), pot_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "This account already has a pot with that name")
        if body.balance is not None:
            pots.set_pot_balance(conn, pot_id, body.balance, plan.today())
        return _pot_out(conn, pot_id)


@router.delete("/pots/{pot_id}", status_code=204)
def delete_pot(pot_id: int):
    with db.session() as conn:
        _get(conn, "pots", pot_id, "pot")
        users = [r["name"] for r in conn.execute("SELECT name FROM recurring WHERE to_pot_id = ? ORDER BY name", (pot_id,))]
        if users:
            raise HTTPException(409, "This pot is still used by: " + ", ".join(users))
        conn.execute("DELETE FROM pots WHERE id = ?", (pot_id,))
    return Response(status_code=204)


# ---------- regular payments ----------

def _validate(conn, r: dict) -> None:
    if not (r["name"] or "").strip():
        raise HTTPException(400, "Name is required")
    if r["amount"] is None or r["amount"] <= 0:
        raise HTTPException(400, "Amount must be more than 0")
    if r["frequency"] not in plan.STEP:
        raise HTTPException(400, "Frequency must be monthly, quarterly or yearly")
    if r["due_day"] is None or not 1 <= r["due_day"] <= 31:
        raise HTTPException(400, "Due day must be between 1 and 31")
    if not MONTH_RE.match(r["start_month"] or ""):
        raise HTTPException(400, "Start month must look like 2026-11")
    _get(conn, "accounts", r["from_account_id"], "account")
    if r["to_account_id"] is not None:
        _get(conn, "accounts", r["to_account_id"], "account")
        if r["to_account_id"] == r["from_account_id"]:
            raise HTTPException(400, "A transfer must go to a different account")
    if r["to_pot_id"] is not None:
        if r["to_account_id"] is None:
            raise HTTPException(400, "Choose the account the pot belongs to")
        if _get(conn, "pots", r["to_pot_id"], "pot")["account_id"] != r["to_account_id"]:
            raise HTTPException(400, "That pot belongs to a different account")


def _recurring_out(row) -> dict:
    out = dict(row)
    out["active"] = bool(out["active"])
    due = plan.next_due(row, plan.today())
    out["next_due"] = due.isoformat() if due else None
    return out


def _write(conn, r: dict, row_id: int | None = None) -> int:
    values = [r[f] if f != "active" else int(bool(r[f])) for f in FIELDS]
    values[0] = values[0].strip()
    if row_id is None:
        cols = ", ".join(FIELDS)
        return conn.execute(f"INSERT INTO recurring({cols}) VALUES ({', '.join('?' * len(FIELDS))})", values).lastrowid
    conn.execute(f"UPDATE recurring SET {', '.join(f + ' = ?' for f in FIELDS)} WHERE id = ?", (*values, row_id))
    return row_id


@router.get("/recurring")
def list_recurring():
    with db.session() as conn:
        return [_recurring_out(r) for r in conn.execute("SELECT * FROM recurring ORDER BY name, id")]


@router.post("/recurring", status_code=201)
def create_recurring(body: RecurringIn):
    with db.session() as conn:
        r = body.model_dump()
        _validate(conn, r)
        # A new item only feeds its pot from today on, even if start_month is in the past.
        pots.reanchor_pots(conn, [r["to_pot_id"]], plan.today())
        row_id = _write(conn, r)
        return _recurring_out(_get(conn, "recurring", row_id, "payment"))


@router.patch("/recurring/{item_id}")
def update_recurring(item_id: int, body: RecurringPatch):
    with db.session() as conn:
        old = _get(conn, "recurring", item_id, "payment")
        r = dict(old) | body.model_dump(exclude_unset=True)
        _validate(conn, r)
        # Freeze pot balances first so the change only affects future due dates.
        pots.reanchor_pots(conn, [old["to_pot_id"], r["to_pot_id"]], plan.today())
        _write(conn, r, item_id)
        return _recurring_out(_get(conn, "recurring", item_id, "payment"))


@router.delete("/recurring/{item_id}", status_code=204)
def delete_recurring(item_id: int):
    with db.session() as conn:
        old = _get(conn, "recurring", item_id, "payment")
        pots.reanchor_pots(conn, [old["to_pot_id"]], plan.today())
        conn.execute("DELETE FROM recurring WHERE id = ?", (item_id,))
    return Response(status_code=204)
