"""Settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


DB_PATH = _path("FINANCE_HUB_DB", "./data/finance.db")
PAYSLIP_DIR = _path("PAYSLIP_DIR", "./data/payslips")
IMPORT_ARCHIVE_DIR = _path("IMPORT_ARCHIVE_DIR", "./data/imports")
# "year":  PAYSLIP_DIR/2026/payslip_2026-03.pdf
# "month": PAYSLIP_DIR/Mar/Entgeltabrechnung_2026-03.pdf (matches the existing NAS archive)
PAYSLIP_LAYOUT = os.environ.get("PAYSLIP_LAYOUT", "year")

# Hostnames/IPs the app answers to (no ports). localhost is always allowed so the
# container healthcheck works. Add the Pi's LAN IP and name, e.g. 192.168.1.50,raspberrypi.local
ALLOWED_HOSTS = sorted(
    {"localhost", "127.0.0.1", "::1"}
    | {h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}
)

BASE_CURRENCY = "EUR"
GBP_EUR = float(os.environ.get("GBP_EUR", "1.15"))
SAVINGS_RATE_TARGET = float(os.environ.get("SAVINGS_RATE_TARGET", "0.20"))
MONTHLY_BUDGET_EUR = float(os.environ.get("MONTHLY_BUDGET_EUR", "3000"))


def to_base(amount: float, currency: str) -> float:
    """Convert to EUR using the manual rate."""
    if currency == "GBP":
        return amount * GBP_EUR
    return amount
