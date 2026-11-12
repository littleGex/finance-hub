"""Importer interface.

Every data source (CSV today, FinTS or an aggregator later) produces
`ParsedTransaction` objects. The rest of the app never cares where they
came from, so a live feed can replace a manual drop without other changes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class ParsedTransaction:
    booked_on: date
    amount: float
    counterparty: str = ""
    description: str = ""
    counterparty_iban: str = ""   # normalised IBAN of the other side, "" if unknown


class Importer(Protocol):
    bank: str

    def sniff(self, text: str) -> bool:
        """True if this importer recognises the file."""

    def parse(self, text: str) -> list[ParsedTransaction]:
        """Parse the decoded file into transactions."""


def decode_bytes(raw: bytes) -> str:
    """Bank exports are UTF-8 or Windows-1252; try both."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def dedup_keys(account_id: int, txs: list[ParsedTransaction]) -> list[str]:
    """Stable keys. Identical rows within one file get an occurrence index so
    two real coffees on the same day are not collapsed, while re-importing the
    same file stays idempotent."""
    seen: dict[str, int] = {}
    keys = []
    for t in txs:
        base = "|".join([
            str(account_id), t.booked_on.isoformat(), f"{t.amount:.2f}",
            t.counterparty.strip().lower(), t.description.strip().lower(),
        ])
        n = seen.get(base, 0)
        seen[base] = n + 1
        keys.append(hashlib.sha256(f"{base}|{n}".encode()).hexdigest())
    return keys
