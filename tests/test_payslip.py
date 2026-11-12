from app import payslip


def test_period_and_amounts_from_text(monkeypatch):
    text = "Entgeltabrechnung Oktober 2026\nGesamt-Brutto 5.120,50\nAuszahlungsbetrag 3.450,00 EUR"
    monkeypatch.setattr(payslip, "extract_text", lambda _: text)
    d = payslip.parse(b"%PDF-fake")
    assert d.period == "2026-10"
    assert d.gross == 5120.50
    assert d.net == 3450.00
    assert not d.needs_review


def test_numeric_period_format(monkeypatch):
    monkeypatch.setattr(payslip, "extract_text", lambda _: "Abrechnungsmonat 03/2026 Netto-Auszahlung 100,00")
    d = payslip.parse(b"%PDF-fake")
    assert d.period == "2026-03" and d.net == 100.0


def test_unreadable_is_flagged(monkeypatch):
    monkeypatch.setattr(payslip, "extract_text", lambda _: "")
    assert payslip.parse(b"%PDF-fake").needs_review
