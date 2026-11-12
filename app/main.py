"""finance-hub API + static front end."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, gamify, payslip
from .importers import csv_banks
from .importers.base import decode_bytes, dedup_keys

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_UPLOAD = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield


app = FastAPI(title="finance-hub", lifespan=lifespan)


class AccountIn(BaseModel):
    name: str
    bank: str = "other"
    currency: str = "EUR"
    opening_balance: float = 0.0


class BalanceIn(BaseModel):
    balance: float


async def _read(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    if not raw:
        raise HTTPException(400, "Empty file")
    return raw


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/accounts")
def list_accounts():
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY name")]


@app.post("/api/accounts", status_code=201)
def create_account(a: AccountIn):
    if a.currency not in ("EUR", "GBP"):
        raise HTTPException(400, "currency must be EUR or GBP")
    with db.session() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO accounts(name, bank, currency, opening_balance) VALUES (?,?,?,?)",
                (a.name.strip(), a.bank, a.currency, a.opening_balance),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An account with that name already exists")
        return {"id": cur.lastrowid, **a.model_dump()}


@app.post("/api/accounts/{account_id}/balance")
def set_balance(account_id: int, b: BalanceIn):
    """Set today's real balance; the opening balance is adjusted to match."""
    with db.session() as conn:
        acc = conn.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not acc:
            raise HTTPException(404, "No such account")
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE account_id=?", (account_id,)
        ).fetchone()["s"]
        opening = round(b.balance - total, 2)
        conn.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (opening, account_id))
        return {"opening_balance": opening}


@app.post("/api/import/{account_id}")
async def import_csv(account_id: int, file: UploadFile = File(...)):
    raw = await _read(file)
    text = decode_bytes(raw)
    with db.session() as conn:
        acc = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not acc:
            raise HTTPException(404, "No such account")
        importer = csv_banks.BY_BANK.get(acc["bank"])
        if importer is None or not importer.sniff(text):
            importer = csv_banks.detect(text)
        if importer is None:
            raise HTTPException(422, "Could not recognise this CSV format")
        try:
            txs = importer.parse(text)
        except (ValueError, KeyError) as e:
            raise HTTPException(422, f"Could not parse file: {e}")

        keys = dedup_keys(account_id, txs)
        new = 0
        for t, k in zip(txs, keys):
            cur = conn.execute(
                """INSERT OR IGNORE INTO transactions
                   (account_id, booked_on, amount, counterparty, description, dedup_key)
                   VALUES (?,?,?,?,?,?)""",
                (account_id, t.booked_on.isoformat(), t.amount, t.counterparty, t.description, k),
            )
            new += cur.rowcount
        conn.execute(
            "INSERT INTO imports(account_id, filename, rows_total, rows_new) VALUES (?,?,?,?)",
            (account_id, file.filename or "upload.csv", len(txs), new),
        )

    config.IMPORT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (file.filename or "upload.csv"))
    (config.IMPORT_ARCHIVE_DIR / f"{account_id}_{safe}").write_bytes(raw)
    return {"format": importer.bank, "rows_total": len(txs), "rows_new": new,
            "rows_duplicate": len(txs) - new}


@app.post("/api/payslips", status_code=201)
async def upload_payslip(file: UploadFile = File(...)):
    raw = await _read(file)
    if not raw.startswith(b"%PDF"):
        raise HTTPException(415, "Please upload a PDF")
    digest = payslip.sha256(raw)
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM payslips WHERE sha256=?", (digest,)).fetchone():
            raise HTTPException(409, "This payslip was already added")
        data = payslip.parse(raw)
        path = payslip.file_payslip(raw, data, file.filename or "payslip.pdf")
        conn.execute(
            """INSERT INTO payslips(sha256, period, gross, net, stored_path, needs_review)
               VALUES (?,?,?,?,?,?)""",
            (digest, data.period, data.gross, data.net, str(path), int(data.needs_review)),
        )
    return {"period": data.period, "gross": data.gross, "net": data.net,
            "needs_review": data.needs_review, "stored_path": str(path)}


@app.get("/api/payslips")
def list_payslips():
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM payslips ORDER BY COALESCE(period,'') DESC, id DESC")]


@app.get("/api/transactions")
def list_transactions(limit: int = 50):
    limit = max(1, min(limit, 500))
    with db.session() as conn:
        rows = conn.execute(
            """SELECT t.*, a.name AS account, a.currency FROM transactions t
               JOIN accounts a ON a.id = t.account_id
               ORDER BY t.booked_on DESC, t.id DESC LIMIT ?""", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/summary")
def get_summary():
    with db.session() as conn:
        return gamify.summary(conn)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
