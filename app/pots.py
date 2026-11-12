"""Pots: named shares of one account's balance (e.g. Mine / Parents / Children).

A pot's balance is the amount last set by hand (the anchor, valid at the END of
anchor_date) plus every planned transfer into the pot that fell due since then.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from . import plan


def pot_balance(conn, pot_id: int, today: date) -> float:
    pot = conn.execute("SELECT anchor_balance, anchor_date FROM pots WHERE id = ?", (pot_id,)).fetchone()
    anchor = date.fromisoformat(pot["anchor_date"])
    total = pot["anchor_balance"]
    for item in conn.execute("SELECT * FROM recurring WHERE to_pot_id = ?", (pot_id,)):
        total += item["amount"] * len(plan.occurrences(item, after=anchor, until=today))
    return round(total, 2)


def set_pot_balance(conn, pot_id: int, balance: float, today: date) -> None:
    conn.execute("UPDATE pots SET anchor_balance = ?, anchor_date = ? WHERE id = ?",
                 (balance, today.isoformat(), pot_id))


def reanchor_pots(conn, pot_ids: Iterable[int | None], today: date) -> None:
    """Freeze the current balance before a plan change, so the change only affects the future."""
    for pot_id in {p for p in pot_ids if p is not None}:
        set_pot_balance(conn, pot_id, pot_balance(conn, pot_id, today), today)


def account_pots(conn, account_id: int, today: date) -> list[dict]:
    rows = conn.execute("SELECT id, name FROM pots WHERE account_id = ? ORDER BY name", (account_id,))
    return [{"id": r["id"], "name": r["name"], "balance": pot_balance(conn, r["id"], today)} for r in rows]
