"""Summary numbers and the game layer: rings, streaks, XP and levels."""
from __future__ import annotations

import math
from datetime import date, timedelta

from . import config

XP_PER_IMPORT = 20
XP_PER_PAYSLIP = 30
XP_PER_SAVING_MONTH = 50


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def prev_month(key: str) -> str:
    y, m = map(int, key.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def level_for(xp: int) -> dict:
    level = int(math.sqrt(xp / 50)) + 1
    floor_xp = 50 * (level - 1) ** 2
    next_xp = 50 * level ** 2
    return {
        "level": level, "xp": xp,
        "into_level": xp - floor_xp, "level_span": next_xp - floor_xp,
        "progress": _clamp((xp - floor_xp) / (next_xp - floor_xp)),
    }


def monthly_cashflow(conn) -> dict[str, dict]:
    """{'YYYY-MM': {'income': x, 'spend': y}} in EUR (all accounts are EUR). Internal transfers are
    not detected in v0, so move money between your own accounts with care."""
    rows = conn.execute(
        "SELECT booked_on, amount FROM transactions"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        k = r["booked_on"][:7]
        bucket = out.setdefault(k, {"income": 0.0, "spend": 0.0})
        amount = r["amount"]
        if amount >= 0:
            bucket["income"] += amount
        else:
            bucket["spend"] += -amount
    return out


def saving_streak(cashflow: dict[str, dict], current: str) -> int:
    """Consecutive completed months (before the current one) with income > spend."""
    streak, key = 0, prev_month(current)
    while key in cashflow and cashflow[key]["income"] > cashflow[key]["spend"]:
        streak += 1
        key = prev_month(key)
    return streak


def summary(conn, today: date | None = None) -> dict:
    today = today or date.today()
    cur = month_key(today)

    accounts = []
    net_worth = 0.0
    for a in conn.execute("SELECT * FROM accounts ORDER BY name").fetchall():
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s, MAX(booked_on) last FROM transactions WHERE account_id=?",
            (a["id"],),
        ).fetchone()
        balance = a["opening_balance"] + total["s"]
        net_worth += balance
        accounts.append({
            "id": a["id"], "name": a["name"], "bank": a["bank"],
            "balance": round(balance, 2), "last_tx": total["last"],
        })

    cashflow = monthly_cashflow(conn)
    this = cashflow.get(cur, {"income": 0.0, "spend": 0.0})
    income, spend = this["income"], this["spend"]
    savings_rate = (income - spend) / income if income > 0 else 0.0

    # Data freshness: share of accounts with an import in the last 7 days.
    cutoff = (today - timedelta(days=7)).isoformat()
    n_acc = len(accounts)
    fresh = conn.execute(
        "SELECT COUNT(DISTINCT account_id) c FROM imports WHERE imported_at >= ?", (cutoff,)
    ).fetchone()["c"]

    rings = {
        "savings": {"value": _clamp(savings_rate / config.SAVINGS_RATE_TARGET) if config.SAVINGS_RATE_TARGET else 0,
                    "label": "Savings rate", "detail": f"{savings_rate * 100:.0f}% of {config.SAVINGS_RATE_TARGET * 100:.0f}% target"},
        "budget": {"value": _clamp(1 - spend / config.MONTHLY_BUDGET_EUR) if config.MONTHLY_BUDGET_EUR else 0,
                   "label": "Budget left", "detail": f"€{spend:,.0f} of €{config.MONTHLY_BUDGET_EUR:,.0f} spent"},
        "fresh": {"value": _clamp(fresh / n_acc) if n_acc else 0.0,
                  "label": "Data fresh", "detail": f"{fresh} of {n_acc} accounts updated this week"},
    }

    # Only imports that brought in new transactions earn XP; re-uploading a file is not progress.
    n_imports = conn.execute("SELECT COUNT(*) c FROM imports WHERE rows_new > 0").fetchone()["c"]
    n_payslips = conn.execute("SELECT COUNT(*) c FROM payslips").fetchone()["c"]
    saving_months = sum(1 for k, v in cashflow.items() if k != cur and v["income"] > v["spend"])
    xp = n_imports * XP_PER_IMPORT + n_payslips * XP_PER_PAYSLIP + saving_months * XP_PER_SAVING_MONTH

    return {
        "net_worth_eur": round(net_worth, 2),
        "accounts": accounts,
        "month": {"key": cur, "income": round(income, 2), "spend": round(spend, 2),
                  "savings_rate": round(savings_rate, 4)},
        "rings": rings,
        "streak_months": saving_streak(cashflow, cur),
        "game": level_for(xp),
    }
