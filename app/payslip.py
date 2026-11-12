"""Payslip drop: read the PDF, extract what we can, file it on the NAS.

German payslips differ a lot between employers, so extraction is best effort.
Anything we cannot read confidently is flagged `needs_review` rather than
guessed; the PDF is filed either way.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
from dataclasses import dataclass

from pypdf import PdfReader

from . import config

MONTHS_DE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

NUM = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"
NET_LABELS = ("auszahlungsbetrag", "auszahlung", "netto-auszahlung", "nettobetrag", "net pay")
GROSS_LABELS = ("gesamt-brutto", "gesamtbrutto", "brutto gesamt", "bruttobezug", "gross pay", "brutto")


@dataclass
class PayslipData:
    period: str | None = None   # YYYY-MM
    gross: float | None = None
    net: float | None = None

    @property
    def needs_review(self) -> bool:
        return self.period is None or self.net is None


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def extract_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _find_amount(text: str, labels: tuple[str, ...]) -> float | None:
    lowered = text.lower()
    for label in labels:
        for m in re.finditer(re.escape(label), lowered):
            tail = text[m.end(): m.end() + 80]
            n = re.search(NUM, tail)
            if n:
                return _num(n.group(1))
    return None


def _find_period(text: str) -> str | None:
    low = text.lower()
    m = re.search(r"(januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(20\d{2})", low)
    if m:
        return f"{m.group(2)}-{MONTHS_DE[m.group(1)]:02d}"
    m = re.search(r"\b(0[1-9]|1[0-2])[./](20\d{2})\b", text)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return None


def parse(pdf_bytes: bytes) -> PayslipData:
    text = extract_text(pdf_bytes)
    return PayslipData(
        period=_find_period(text),
        gross=_find_amount(text, GROSS_LABELS),
        net=_find_amount(text, NET_LABELS),
    )


def sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def file_payslip(pdf_bytes: bytes, data: PayslipData, original_name: str):
    """Write the PDF into PAYSLIP_DIR/<year>/ and return its path."""
    year = data.period[:4] if data.period else "unsorted"
    folder = config.PAYSLIP_DIR / year
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"payslip_{data.period}" if data.period else re.sub(r"[^\w.-]", "_", original_name.rsplit(".", 1)[0])
    target = folder / f"{stem}.pdf"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{stem}_{n}.pdf"
    with open(target, "wb") as fh:
        shutil.copyfileobj(io.BytesIO(pdf_bytes), fh)
    return target
