"""Internal transfers between own accounts.

A transaction whose counterparty IBAN is one of our own accounts is a transfer.
Its counterpart on the other account (whose export may lack the IBAN) is found by
pairing: opposite amount, booked within PAIR_WINDOW_DAYS, closest date first.
Transfers count as neither income nor spending.
"""
from __future__ import annotations

import re
from datetime import date

IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
PAIR_WINDOW_DAYS = 3


def is_plausible_iban(s: str) -> bool:
    return bool(IBAN_RE.match(s))


def normalize_iban(s: str | None) -> str | None:
    """Uppercase without whitespace; None if empty or not IBAN-shaped (e.g. old account numbers)."""
    if not s:
        return None
    s = re.sub(r"\s+", "", s).upper()
    return s if is_plausible_iban(s) else None


def mark_transfers(conn) -> int:
    """Recompute is_transfer for every transaction. Returns how many are marked."""
    conn.execute("UPDATE transactions SET is_transfer = 0")
    own = {r["iban"]: r["id"] for r in conn.execute("SELECT id, iban FROM accounts WHERE iban IS NOT NULL")}
    if not own:
        return 0

    direct = [
        r for r in conn.execute(
            "SELECT id, account_id, booked_on, amount, counterparty_iban FROM transactions "
            "WHERE counterparty_iban IS NOT NULL ORDER BY booked_on, id")
        if own.get(r["counterparty_iban"]) not in (None, r["account_id"])
    ]
    target_of = {r["id"]: own[r["counterparty_iban"]] for r in direct}
    marked = set(target_of)
    paired: set[int] = set()   # transactions whose other leg has been found

    for r in direct:
        if r["id"] in paired:          # already matched as the other leg of an earlier transfer
            continue
        day = date.fromisoformat(r["booked_on"])
        candidates = [
            c for c in conn.execute(
                "SELECT id, booked_on FROM transactions WHERE account_id = ? AND amount = ? "
                "AND julianday(booked_on) BETWEEN julianday(?) - ? AND julianday(?) + ?",
                (target_of[r["id"]], -r["amount"], r["booked_on"], PAIR_WINDOW_DAYS, r["booked_on"], PAIR_WINDOW_DAYS))
            if c["id"] not in paired
            # a direct leg can only be this transfer's partner if it points back at our account
            and target_of.get(c["id"], r["account_id"]) == r["account_id"]
        ]
        if candidates:
            best = min(candidates, key=lambda c: (abs((date.fromisoformat(c["booked_on"]) - day).days), c["id"]))
            paired.update((r["id"], best["id"]))
            marked.add(best["id"])

    conn.executemany("UPDATE transactions SET is_transfer = 1 WHERE id = ?", [(i,) for i in marked])
    return len(marked)
