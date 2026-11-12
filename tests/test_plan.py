from datetime import date

import pytest

from app.plan import next_due, occurrences, plan_summary, upcoming
from tests.conftest import add_account, add_item, add_pot


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


@pytest.fixture()
def planned(conn):
    giro = add_account(conn, "Giro")
    spar = add_account(conn, "Sparkonto")
    kids = add_pot(conn, spar, "Children", 0.0, "2026-11-01")
    add_item(conn, "Car insurance", 600.0, giro, frequency="yearly", due_day=20, start_month="2026-11")
    add_item(conn, "Phone", 50.0, giro, due_day=3)
    add_item(conn, "To children", 100.0, giro, due_day=25, to_account_id=spar, to_pot_id=kids)
    add_item(conn, "Paused gym", 40.0, giro, due_day=15, active=0)
    return conn


INCOME = {"2026-07": {"income": 1000.0, "spend": 0}, "2026-08": {"income": 3000.0, "spend": 0},
          "2026-09": {"income": 3000.0, "spend": 0}, "2026-10": {"income": 3300.0, "spend": 0},
          "2026-11": {"income": 9999.0, "spend": 0}}


def test_plan_counts_full_amounts_in_due_month(planned):
    p = plan_summary(planned, date(2026, 11, 12), INCOME)
    assert p["bills_this_month"] == 650.0
    assert p["saving_this_month"] == 100.0
    assert p["still_to_come"] == 700.0            # insurance (20th) + transfer (25th); phone (3rd) passed


def test_yearly_bill_absent_in_other_months(planned):
    assert plan_summary(planned, date(2026, 12, 12), INCOME)["bills_this_month"] == 50.0


def test_avg_income_uses_last_three_completed_months(planned):
    p = plan_summary(planned, date(2026, 11, 12), INCOME)
    assert p["avg_income"] == pytest.approx(3100.0)   # Aug, Sep, Oct; November in progress
    assert p["left_after_plan"] == pytest.approx(3100.0 - 650.0 - 100.0)


def test_avg_income_skips_months_without_data(planned):
    sparse = {"2026-06": {"income": 2000.0, "spend": 0}, "2026-10": {"income": 4000.0, "spend": 0}}
    assert plan_summary(planned, date(2026, 11, 12), sparse)["avg_income"] == pytest.approx(3000.0)


def test_empty_plan(conn):
    assert plan_summary(conn, date(2026, 11, 12), {}) == {
        "bills_this_month": 0.0, "saving_this_month": 0.0, "still_to_come": 0.0,
        "avg_income": None, "left_after_plan": None}


def test_upcoming_sorted_with_targets(planned):
    items = upcoming(planned, date(2026, 11, 12))
    assert [u["date"] for u in items][:3] == ["2026-11-20", "2026-11-25", "2026-12-03"]
    transfer = items[1]
    assert transfer["kind"] == "transfer" and transfer["to_account"] == "Sparkonto" and transfer["to_pot"] == "Children"
    assert items[0]["kind"] == "bill" and items[0]["to_account"] is None
    assert all(u["name"] != "Paused gym" for u in items)
    assert all(u["date"] <= "2027-01-11" for u in items) and len(items) <= 10
