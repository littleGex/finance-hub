"""Settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


DB_PATH = _path("FINANCE_HUB_DB", "./data/finance.db")
PAYSLIP_DIR = _path("PAYSLIP_DIR", "./data/payslips")
IMPORT_ARCHIVE_DIR = _path("IMPORT_ARCHIVE_DIR", "./data/imports")

BASE_CURRENCY = "EUR"
GBP_EUR = float(os.environ.get("GBP_EUR", "1.15"))
SAVINGS_RATE_TARGET = float(os.environ.get("SAVINGS_RATE_TARGET", "0.20"))
MONTHLY_BUDGET_EUR = float(os.environ.get("MONTHLY_BUDGET_EUR", "3000"))


def to_base(amount: float, currency: str) -> float:
    """Convert to EUR using the manual rate."""
    if currency == "GBP":
        return amount * GBP_EUR
    return amount
