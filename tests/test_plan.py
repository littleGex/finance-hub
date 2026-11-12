from datetime import date

from app.plan import next_due, occurrences


def it(freq, day, start, active=1):
    return {"frequency": freq, "due_day": day, "start_month": start, "active": active}


def test_monthly_clamps_to_month_end():
    assert occurrences(it("monthly", 31, "2026-01"), date(2026, 1, 1), date(2026, 4, 30)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_leap_year_february():
    assert occurrences(it("monthly", 29, "2028-02"), date(2028, 1, 31), date(2028, 2, 29)) == [date(2028, 2, 29)]


def test_quarterly_cycle_from_start_month():
    assert occurrences(it("quarterly", 15, "2026-11"), date(2026, 10, 31), date(2027, 6, 30)) == [
        date(2026, 11, 15), date(2027, 2, 15), date(2027, 5, 15)]


def test_yearly_absent_in_other_months():
    assert occurrences(it("yearly", 1, "2026-03"), date(2026, 3, 31), date(2027, 2, 28)) == []


def test_future_start_month_yields_nothing_before_it():
    assert occurrences(it("monthly", 5, "2027-01"), date(2026, 11, 1), date(2026, 12, 31)) == []


def test_paused_item_yields_nothing():
    assert occurrences(it("monthly", 5, "2026-01", active=0), date(2026, 1, 1), date(2026, 12, 31)) == []


def test_after_is_exclusive_until_inclusive():
    assert occurrences(it("monthly", 10, "2026-01"), date(2026, 3, 10), date(2026, 4, 10)) == [date(2026, 4, 10)]


def test_next_due_yearly_rolls_to_next_year():
    assert next_due(it("yearly", 15, "2026-03"), date(2026, 11, 12)) == date(2027, 3, 15)


def test_next_due_today_counts():
    assert next_due(it("monthly", 12, "2026-01"), date(2026, 11, 12)) == date(2026, 11, 12)


def test_next_due_paused_is_none():
    assert next_due(it("monthly", 12, "2026-01", active=0), date(2026, 11, 12)) is None
