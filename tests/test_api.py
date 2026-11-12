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
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    import importlib
    from app import config, db, main
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def make_account(c, name, bank):
    r = c.post("/api/accounts", json={"name": name, "bank": bank})
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


def test_net_worth_sums_accounts_in_eur(client):
    a = make_account(client, "Sparkasse Giro", "sparkasse")
    b = make_account(client, "BoS Tagesgeld", "bos")
    client.post(f"/api/accounts/{a}/balance", json={"balance": 1000})
    client.post(f"/api/accounts/{b}/balance", json={"balance": 2500.50})
    s = client.get("/api/summary").json()
    assert s["net_worth_eur"] == 3500.50
    assert "fx" not in s


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


def test_reimporting_same_file_earns_no_xp(client):
    acc = make_account(client, "Sparkasse Giro", "sparkasse")
    data = (SAMPLES / "sparkasse_sample.csv").read_bytes()
    client.post(f"/api/import/{acc}", files={"file": ("s.csv", data)})
    xp_after_first = client.get("/api/summary").json()["game"]["xp"]
    for _ in range(5):
        client.post(f"/api/import/{acc}", files={"file": ("s.csv", data)})
    assert client.get("/api/summary").json()["game"]["xp"] == xp_after_first


def test_same_filename_different_content_both_archived(client, tmp_path):
    acc = make_account(client, "Sparkasse Giro", "sparkasse")
    data = (SAMPLES / "sparkasse_sample.csv").read_bytes()
    lines = data.splitlines(keepends=True)
    client.post(f"/api/import/{acc}", files={"file": ("Umsaetze.csv", data)})
    client.post(f"/api/import/{acc}", files={"file": ("Umsaetze.csv", b"".join(lines[:-1]))})
    archived = sorted((tmp_path / "imports").iterdir())
    assert len(archived) == 2
    assert all(p.name.endswith("Umsaetze.csv") for p in archived)


def test_unknown_host_rejected(client):
    r = client.get("/api/summary", headers={"host": "evil.example"})
    assert r.status_code == 400


def test_cross_origin_post_rejected(client):
    r = client.post("/api/accounts", json={"name": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/accounts", json={"name": "x"}, headers={"origin": "null"})
    assert r.status_code == 403


def test_same_origin_post_allowed(client):
    r = client.post("/api/accounts", json={"name": "x"}, headers={"origin": "http://testserver"})
    assert r.status_code == 201
