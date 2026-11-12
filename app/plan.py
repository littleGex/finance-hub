"""Regular payments: due dates and the monthly plan.

Every amount counts in full on its due date; nothing is spread over months.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Mapping

STEP: dict[str, int] = {"monthly": 1, "quarterly": 3, "yearly": 12}


def today() -> date:
    """Wrapped so tests can monkeypatch the current date."""
    return date.today()


def occurrences(item: Mapping, after: date, until: date) -> list[date]:
    """Due dates d with after < d <= until. Paused items have none."""
    if not item["active"]:
        return []
    step = STEP[item["frequency"]]
    year, month = map(int, item["start_month"].split("-"))
    index = year * 12 + (month - 1)                       # months since year 0
    out = []
    while True:
        y, m = divmod(index, 12)
        m += 1
        if date(y, m, 1) > until:
            return out
        d = date(y, m, min(item["due_day"], calendar.monthrange(y, m)[1]))
        if after < d <= until:
            out.append(d)
        index += step


def next_due(item: Mapping, today: date) -> date | None:
    """First due date on or after today (searching one year ahead)."""
    found = occurrences(item, today - timedelta(days=1), today + timedelta(days=366))
    return found[0] if found else None


def _month_bounds(today: date) -> tuple[date, date]:
    """(last day of previous month, last day of this month) for occurrences(after, until)."""
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return first - timedelta(days=1), last


def _avg_income(cashflow: dict, today: date) -> float | None:
    current = today.strftime("%Y-%m")
    completed = sorted(k for k in cashflow if k < current)[-3:]
    if not completed:
        return None
    return sum(cashflow[k]["income"] for k in completed) / len(completed)


def plan_summary(conn, today: date, cashflow: dict) -> dict:
    after, until = _month_bounds(today)
    bills = saving = still = 0.0
    for item in conn.execute("SELECT * FROM recurring"):
        for d in occurrences(item, after, until):
            if item["to_account_id"] is None:
                bills += item["amount"]
            else:
                saving += item["amount"]
            if d > today:
                still += item["amount"]
    avg = _avg_income(cashflow, today)
    return {
        "bills_this_month": round(bills, 2),
        "saving_this_month": round(saving, 2),
        "still_to_come": round(still, 2),
        "avg_income": None if avg is None else round(avg, 2),
        "left_after_plan": None if avg is None else round(avg - bills - saving, 2),
    }


def upcoming(conn, today: date, days: int = 60, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """SELECT r.*, a.name AS to_account, p.name AS to_pot FROM recurring r
           LEFT JOIN accounts a ON a.id = r.to_account_id
           LEFT JOIN pots p ON p.id = r.to_pot_id""").fetchall()
    out = [
        {"recurring_id": r["id"], "name": r["name"], "date": d.isoformat(), "amount": r["amount"],
         "kind": "bill" if r["to_account_id"] is None else "transfer",
         "to_account": r["to_account"], "to_pot": r["to_pot"]}
        for r in rows
        for d in occurrences(r, today - timedelta(days=1), today + timedelta(days=days))
    ]
    out.sort(key=lambda u: (u["date"], u["name"]))
    return out[:limit]
