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


def _period(monkeypatch, text):
    monkeypatch.setattr(payslip, "extract_text", lambda _: text)
    return payslip.parse(b"%PDF-fake").period


def test_entry_date_is_not_mistaken_for_period(monkeypatch):
    text = "Eintrittsdatum 01.04.2019\nAbrechnungsmonat 03/2026\nAuszahlungsbetrag 100,00"
    assert _period(monkeypatch, text) == "2026-03"


def test_labelled_period_wins_over_earlier_month_name(monkeypatch):
    text = "Eintritt April 2019\nAbrechnungszeitraum: März 2026"
    assert _period(monkeypatch, text) == "2026-03"


def test_labelled_date_range_period(monkeypatch):
    text = "Eintrittsdatum 01.04.2019\nAbrechnungszeitraum 01.03.2026 - 31.03.2026"
    assert _period(monkeypatch, text) == "2026-03"


def test_full_dates_alone_are_not_periods(monkeypatch):
    assert _period(monkeypatch, "Eintrittsdatum 01.04.2019 Auszahlung 100,00") is None


def test_conflicting_unlabelled_periods_need_review(monkeypatch):
    monkeypatch.setattr(payslip, "extract_text", lambda _: "April 2019\n03/2026\nAuszahlungsbetrag 100,00")
    d = payslip.parse(b"%PDF-fake")
    assert d.period is None and d.needs_review


def test_month_layout_matches_nas_archive(monkeypatch, tmp_path):
    from app import config
    monkeypatch.setattr(config, "PAYSLIP_DIR", tmp_path)
    monkeypatch.setattr(config, "PAYSLIP_LAYOUT", "month")
    p = payslip.file_payslip(b"%PDF", payslip.PayslipData(period="2026-09"), "x.pdf")
    assert p == tmp_path / "Sept" / "Entgeltabrechnung_2026-09.pdf"
    p2 = payslip.file_payslip(b"%PDF", payslip.PayslipData(period="2026-09"), "x.pdf")
    assert p2.name == "Entgeltabrechnung_2026-09_2.pdf"   # never overwrites


def test_year_layout_default(monkeypatch, tmp_path):
    from app import config
    monkeypatch.setattr(config, "PAYSLIP_DIR", tmp_path)
    monkeypatch.setattr(config, "PAYSLIP_LAYOUT", "year")
    p = payslip.file_payslip(b"%PDF", payslip.PayslipData(period="2026-03"), "x.pdf")
    assert p == tmp_path / "2026" / "payslip_2026-03.pdf"
