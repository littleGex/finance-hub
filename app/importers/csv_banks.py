"""CSV importers for Sparkasse, ING (DE) and Bank of Scotland.

Parsers are header-driven and tolerant, but export layouts change. Check them
against a real export from each bank and adjust the column names below if a
bank has changed its format.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from .base import ParsedTransaction


def _de_number(s: str) -> float:
    s = s.strip().replace(".", "").replace(",", ".")
    return float(s) if s else 0.0


def _en_number(s: str) -> float:
    s = s.strip().replace(",", "")
    return float(s) if s else 0.0


def _date(s: str, formats: tuple[str, ...]) -> date:
    s = s.strip()
    for f in formats:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {s!r}")


def _find_header(lines: list[str], required: tuple[str, ...], delim: str) -> int:
    for i, line in enumerate(lines):
        cells = [c.strip().strip('"') for c in line.split(delim)]
        if all(r in cells for r in required):
            return i
    raise ValueError("Header row not found")


class SparkasseCSV:
    """Sparkasse 'CSV-CAMT' export: semicolon, dd.mm.yy, decimal comma."""
    bank = "sparkasse"
    REQUIRED = ("Buchungstag", "Verwendungszweck", "Betrag")

    def sniff(self, text: str) -> bool:
        try:
            _find_header(text.splitlines(), self.REQUIRED, ";")
            return "Auftragskonto" in text.splitlines()[0] or "Beguenstigter/Zahlungspflichtiger" in text
        except ValueError:
            return False

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()
        h = _find_header(lines, self.REQUIRED, ";")
        reader = csv.DictReader(lines[h:], delimiter=";", quotechar='"')
        out = []
        for r in reader:
            if not (r.get("Buchungstag") or "").strip():
                continue
            out.append(ParsedTransaction(
                booked_on=_date(r["Buchungstag"], ("%d.%m.%y", "%d.%m.%Y")),
                amount=_de_number(r["Betrag"]),
                counterparty=(r.get("Beguenstigter/Zahlungspflichtiger") or "").strip(),
                description=(r.get("Verwendungszweck") or "").strip(),
            ))
        return out


class IngCSV:
    """ING-DiBa export: metadata block, then a header row; semicolon, dd.mm.yyyy."""
    bank = "ing"
    REQUIRED = ("Buchung", "Verwendungszweck", "Betrag")

    def sniff(self, text: str) -> bool:
        try:
            _find_header(text.splitlines(), self.REQUIRED, ";")
            return "Auftraggeber/Empf" in text
        except ValueError:
            return False

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()
        h = _find_header(lines, self.REQUIRED, ";")
        reader = csv.DictReader(lines[h:], delimiter=";", quotechar='"')
        party_key = next(k for k in reader.fieldnames if k.startswith("Auftraggeber/Empf"))
        out = []
        for r in reader:
            if not (r.get("Buchung") or "").strip():
                continue
            out.append(ParsedTransaction(
                booked_on=_date(r["Buchung"], ("%d.%m.%Y", "%d.%m.%y")),
                amount=_de_number(r["Betrag"]),
                counterparty=(r.get(party_key) or "").strip(),
                description=(r.get("Verwendungszweck") or "").strip(),
            ))
        return out


class BankOfScotlandCSV:
    """Bank of Scotland: comma separated, dd/mm/yyyy, separate debit/credit columns."""
    bank = "bos"
    REQUIRED = ("Transaction Date", "Transaction Description", "Debit Amount", "Credit Amount")

    def sniff(self, text: str) -> bool:
        try:
            _find_header(text.splitlines(), self.REQUIRED, ",")
            return True
        except ValueError:
            return False

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()
        h = _find_header(lines, self.REQUIRED, ",")
        reader = csv.DictReader(lines[h:])
        out = []
        for r in reader:
            if not (r.get("Transaction Date") or "").strip():
                continue
            debit = _en_number(r.get("Debit Amount") or "")
            credit = _en_number(r.get("Credit Amount") or "")
            out.append(ParsedTransaction(
                booked_on=_date(r["Transaction Date"], ("%d/%m/%Y", "%d/%m/%y")),
                amount=credit - debit,
                counterparty="",
                description=(r.get("Transaction Description") or "").strip(),
            ))
        return out


IMPORTERS = [SparkasseCSV(), IngCSV(), BankOfScotlandCSV()]
BY_BANK = {i.bank: i for i in IMPORTERS}


def detect(text: str):
    for imp in IMPORTERS:
        if imp.sniff(text):
            return imp
    return None
