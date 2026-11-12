import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_HUB_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("PAYSLIP_DIR", str(tmp_path / "payslips"))
    monkeypatch.setenv("IMPORT_ARCHIVE_DIR", str(tmp_path / "imports"))
    import importlib
    from app import config, db, main
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def make_account(c, name, bank, currency="EUR"):
    r = c.post("/api/accounts", json={"name": name, "bank": bank, "currency": currency})
    assert r.status_code == 201
    return r.json()["id"]


def test_import_is_idempotent(client):
    acc = make_account(client, "Sparkasse Giro", "sparkasse")
    data = (SAMPLES / "sparkasse_sample.csv").read_bytes()
    r1 = client.post(f"/api/import/{acc}", files={"file": ("s.csv", data)})
    assert r1.json()["rows_new"] == 10
    r2 = client.post(f"/api/import/{acc}", files={"file": ("s.csv", data)})
    assert r2.json()["rows_new"] == 0
    assert r2.json()["rows_duplicate"] == 10


def test_unknown_csv_rejected(client):
    acc = make_account(client, "X", "sparkasse")
    r = client.post(f"/api/import/{acc}", files={"file": ("x.csv", b"a,b\n1,2\n")})
    assert r.status_code == 422


def test_set_balance_anchors_net_worth(client):
    acc = make_account(client, "Sparkasse Giro", "sparkasse")
    client.post(f"/api/import/{acc}", files={"file": ("s.csv", (SAMPLES / "sparkasse_sample.csv").read_bytes())})
    client.post(f"/api/accounts/{acc}/balance", json={"balance": 5000})
    s = client.get("/api/summary").json()
    assert s["accounts"][0]["balance"] == 5000
    assert s["net_worth_eur"] == 5000


def test_gbp_account_converted_with_manual_rate(client):
    acc = make_account(client, "BoS", "bos", "GBP")
    client.post(f"/api/accounts/{acc}/balance", json={"balance": 1000})
    s = client.get("/api/summary").json()
    assert s["net_worth_eur"] == pytest.approx(1000 * 1.15)


def test_summary_empty_state(client):
    s = client.get("/api/summary").json()
    assert s["net_worth_eur"] == 0
    assert s["game"]["level"] == 1


def test_payslip_rejects_non_pdf_and_files_pdf(client, tmp_path):
    assert client.post("/api/payslips", files={"file": ("x.pdf", b"not a pdf")}).status_code == 415
    from pypdf import PdfWriter
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.write(buf)
    r = client.post("/api/payslips", files={"file": ("lohn.pdf", buf.getvalue())})
    assert r.status_code == 201
    body = r.json()
    assert body["needs_review"] is True          # blank page: nothing readable
    assert Path(body["stored_path"]).exists()
    assert client.post("/api/payslips", files={"file": ("lohn.pdf", buf.getvalue())}).status_code == 409
