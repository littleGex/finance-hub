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


MONTH_NAME_RE = re.compile(
    r"\b(januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(20\d{2})\b")
# "03/2026" or "03.2026", but not the tail of a full date like "01.04.2019".
MONTH_NUM_RE = re.compile(r"(?<![\d./])(0[1-9]|1[0-2])[./](20\d{2})\b")
# After a period label, a full date (start of a range) also counts.
LABELLED_NUM_RE = re.compile(r"(?<![\d./])(?:\d{1,2}[./])?(0[1-9]|1[0-2])[./](20\d{2})\b")
PERIOD_LABELS = (
    "abrechnungsmonat", "abrechnungszeitraum", "abrechnungsperiode", "abrechnung für", "abrechnung fuer",
    "entgeltabrechnung", "gehaltsabrechnung", "lohnabrechnung", "verdienstabrechnung", "zeitraum", "pay period",
)


def _period_from(m: re.Match) -> str:
    month, year = m.group(1), m.group(2)
    return f"{year}-{MONTHS_DE[month]:02d}" if month in MONTHS_DE else f"{year}-{month}"


def _find_period(text: str) -> str | None:
    """Payslips also carry entry dates, birth dates and print dates, so:
    1. a month right after a period label wins;
    2. otherwise use the month only if every unlabelled candidate agrees;
    3. if they disagree, return None so the payslip is flagged for review."""
    low = text.lower()
    for label in PERIOD_LABELS:
        for lm in re.finditer(re.escape(label), low):
            tail = low[lm.end(): lm.end() + 40]
            hits = [m for m in (MONTH_NAME_RE.search(tail), LABELLED_NUM_RE.search(tail)) if m]
            if hits:
                return _period_from(min(hits, key=lambda m: m.start()))

    candidates = {_period_from(m) for m in MONTH_NAME_RE.finditer(low)}
    candidates |= {_period_from(m) for m in MONTH_NUM_RE.finditer(low)}
    return candidates.pop() if len(candidates) == 1 else None


def parse(pdf_bytes: bytes) -> PayslipData:
    text = extract_text(pdf_bytes)
    return PayslipData(
        period=_find_period(text),
        gross=_find_amount(text, GROSS_LABELS),
        net=_find_amount(text, NET_LABELS),
    )


def sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


MONTH_FOLDERS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")


def _target_folder_and_stem(data: PayslipData, original_name: str) -> tuple[str, str]:
    if not data.period:
        return "unsorted", re.sub(r"[^\w.-]", "_", original_name.rsplit(".", 1)[0])
    if config.PAYSLIP_LAYOUT == "month":
        return MONTH_FOLDERS[int(data.period[5:7]) - 1], f"Entgeltabrechnung_{data.period}"
    return data.period[:4], f"payslip_{data.period}"


def file_payslip(pdf_bytes: bytes, data: PayslipData, original_name: str):
    """Write the PDF into PAYSLIP_DIR (layout per PAYSLIP_LAYOUT) and return its path."""
    sub, stem = _target_folder_and_stem(data, original_name)
    folder = config.PAYSLIP_DIR / sub
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}.pdf"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{stem}_{n}.pdf"
    with open(target, "wb") as fh:
        shutil.copyfileobj(io.BytesIO(pdf_bytes), fh)
    return target
