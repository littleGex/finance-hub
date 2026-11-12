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
