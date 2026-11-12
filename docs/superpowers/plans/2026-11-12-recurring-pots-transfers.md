# Regular Payments, Pots and Internal Transfers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a planning view of regular payments, pots inside accounts, and IBAN-based internal-transfer detection, so the dashboard shows where the money really is right now.

**Architecture:** Pure date/plan logic in `app/plan.py`, pot state in `app/pots.py`, transfer detection in `app/transfers.py`; new HTTP routes in `app/routes_plan.py` (an `APIRouter` included by `main.py`). Schema changes are additive and applied by `db.init()` on startup. The front end gains a bottom tab bar; the Accounts tab lives in a new `web/accounts.js`.

**Tech Stack:** Python 3.12, FastAPI, SQLite (`sqlite3`), pytest + `fastapi.testclient`; vanilla JS PWA (no build step).

**Spec:** `docs/superpowers/specs/2026-11-12-recurring-pots-transfers-design.md`

## Global Constraints

- All money is EUR. Every amount counts in full on its due date; nothing is spread across months.
- Frequencies: exactly `monthly` | `quarterly` | `yearly` (step 1 / 3 / 12 months). `due_day` 1–31, clamped to month end. `start_month` is `YYYY-MM`.
- Pot anchor = balance at the **end** of `anchor_date`; an item due on the anchor date is not added again.
- Transfer pairing window: ±3 days, amount exactly opposite, closest date first, then lowest id; a transaction is paired at most once.
- `upcoming`: today inclusive through today + 60 days, max 10 entries.
- `avg_income`: last 3 **completed** months that have data, transfers excluded; `null` if none.
- IBANs stored normalised (uppercase, no spaces). Plausibility regex: `^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$`.
- `counterparty_iban` is NOT part of the dedup key.
- Unchanged: budget ring, XP, streaks, net worth formula.
- No `innerHTML` in the front end; build DOM with the existing `el()` helper. No browser `alert/confirm/prompt` in new code.
- Run tests with `.venv/bin/pytest -q`. Every task ends with the full suite green.

## Review Focus

1. Sparkasse `Kontonummer` holding an old-style account number or blank (not an IBAN) → stored as NULL, never matched. Test in Task 4.
2. IBAN typed with spaces/lowercase in the UI (`de12 3456 …`) → normalised and matches imported IBANs. Test in Task 4.
3. Pot set by hand, then the feeding item edited the same day → no double count and no lost contribution. Test in Task 3.
4. Editing a transfer item's `to_account_id` while it still carries a `to_pot_id` of the old account → 400, not a silent mismatch. Test in Task 6.
5. Fresh install with no recurring items, no pots, no transactions → summary returns zeros, `avg_income`/`left_after_plan` null, UI shows "—". Test in Task 5.

---

### Task 1: Schema migration

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db.py` (create)

**Interfaces:**
- Produces: tables `pots`, `recurring`; columns `accounts.iban`, `transactions.counterparty_iban`, `transactions.is_transfer` (INTEGER NOT NULL DEFAULT 0); partial unique index `idx_accounts_iban ON accounts(iban) WHERE iban IS NOT NULL`; unique `(account_id, name)` on `pots`. `db.init()` stays the single entry point.

- [ ] **Step 1: Write failing tests**

```python
def test_init_migrates_v0_database(tmp_path, monkeypatch):
    # build a v0 DB with the original CREATE statements (copy from git show 9a62643:app/db.py),
    # insert one account and one transaction, then run db.init()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert {"counterparty_iban", "is_transfer"} <= cols
    assert "iban" in {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1   # rows intact
    assert conn.execute("SELECT is_transfer FROM transactions").fetchone()[0] == 0

def test_init_is_idempotent(tmp_path, monkeypatch):
    db.init(); db.init()   # no "duplicate column" error

def test_iban_unique_but_nulls_allowed(...):
    # two accounts with iban NULL ok; two with same iban -> sqlite3.IntegrityError
```

Point `config.DB_PATH` at `tmp_path` via `monkeypatch.setattr(config, "DB_PATH", ...)`.

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_db.py` — expect FAIL (missing columns).
- [ ] **Step 3: Implement** in `app/db.py`: add the two `CREATE TABLE IF NOT EXISTS` blocks to `SCHEMA` (columns exactly as in the spec, FKs to `accounts(id)` / `pots(id)`), and `_add_column(conn, table: str, column: str, decl: str) -> None` that checks `PRAGMA table_info` before `ALTER TABLE … ADD COLUMN`. `init()` runs `SCHEMA`, then the three `_add_column` calls, then `CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_iban …`.
- [ ] **Step 4: Run** full suite — expect all PASS.
- [ ] **Step 5: Commit** `feat: schema for pots, recurring items and transfer flags`

---

### Task 2: Due-date engine

**Files:**
- Create: `app/plan.py`
- Test: `tests/test_plan.py` (create)

**Interfaces:**
- Produces:
  - `STEP: dict[str, int] = {"monthly": 1, "quarterly": 3, "yearly": 12}`
  - `occurrences(item: Mapping, after: date, until: date) -> list[date]` — `item` has keys `frequency`, `due_day`, `start_month`, `active`; returns sorted dates with `after < d <= until`; `[]` when `active` is falsy.
  - `next_due(item: Mapping, today: date) -> date | None` — first occurrence `>= today`, searching up to `today + 366 days`.
  - `today() -> date` — wraps `date.today()`; routes call this so tests can monkeypatch `app.plan.today`.

- [ ] **Step 1: Write failing tests** (item helper `it(freq, day, start, active=1)`):

```python
assert occurrences(it("monthly", 31, "2026-01"), date(2026,1,1), date(2026,4,30)) == \
    [date(2026,1,31), date(2026,2,28), date(2026,3,31), date(2026,4,30)]
assert occurrences(it("monthly", 29, "2028-02"), date(2028,1,31), date(2028,2,29)) == [date(2028,2,29)]  # leap year
assert occurrences(it("quarterly", 15, "2026-11"), date(2026,10,31), date(2027,6,30)) == \
    [date(2026,11,15), date(2027,2,15), date(2027,5,15)]
assert occurrences(it("yearly", 1, "2026-03"), date(2026,3,31), date(2027,2,28)) == []          # absent in other months
assert occurrences(it("monthly", 5, "2027-01"), date(2026,11,1), date(2026,12,31)) == []        # future start
assert occurrences(it("monthly", 5, "2026-01", active=0), date(2026,1,1), date(2026,12,31)) == []
assert occurrences(it("monthly", 10, "2026-01"), date(2026,3,10), date(2026,4,10)) == [date(2026,4,10)]  # `after` exclusive
assert next_due(it("yearly", 15, "2026-03"), date(2026,11,12)) == date(2027,3,15)
assert next_due(it("monthly", 12, "2026-01"), date(2026,11,12)) == date(2026,11,12)            # today counts
```

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_plan.py` — expect FAIL (module missing).
- [ ] **Step 3: Implement** `occurrences`, `next_due`, `today` in `app/plan.py`. Iterate month indices from `start_month` by `STEP[frequency]`; clamp the day with `calendar.monthrange`; stop once the month start is past `until`.
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** `feat: due-date engine for regular payments`

---

### Task 3: Pots

**Files:**
- Create: `app/pots.py`
- Test: `tests/test_pots.py` (create)

**Interfaces:**
- Consumes: `plan.occurrences` (Task 2); tables from Task 1.
- Produces:
  - `pot_balance(conn, pot_id: int, today: date) -> float` — `anchor_balance` + Σ `amount` of transfer items with `to_pot_id = pot_id` over `occurrences(item, after=anchor_date, until=today)`, rounded to 2 dp.
  - `set_pot_balance(conn, pot_id: int, balance: float, today: date) -> None` — anchor = (`balance`, `today`).
  - `reanchor_pots(conn, pot_ids: Iterable[int | None], today: date) -> None` — sets each non-None pot's anchor to its current `pot_balance`, dated `today`.
  - `account_pots(conn, account_id: int, today: date) -> list[dict]` — `[{"id", "name", "balance"}]` ordered by name.

- [ ] **Step 1: Write failing tests** (insert rows directly; transfer item €100 monthly, due day 1, start `2026-01`, into pot anchored at €500 on `2026-09-15`):

```python
assert pot_balance(conn, pot, date(2026,11,12)) == 700.0    # Oct 1 + Nov 1
set_pot_balance(conn, pot, 650.0, date(2026,11,12))
assert pot_balance(conn, pot, date(2026,12,1)) == 750.0
# anchor on a due date excludes that day's item
set_pot_balance(conn, pot, 650.0, date(2026,12,1)); assert pot_balance(conn, pot, date(2026,12,1)) == 650.0
# Review Focus 3: re-anchor then change the item the same day
reanchor_pots(conn, [pot], date(2026,12,1)); <UPDATE amount=200>
assert pot_balance(conn, pot, date(2026,12,1)) == 650.0      # no double count, nothing lost
assert pot_balance(conn, pot, date(2027,1,1)) == 850.0       # new amount from next due date
# paused item contributes nothing after re-anchor; a bill item (no to_pot) never affects pots
reanchor_pots(conn, [None], date(2026,12,1))                 # no-op, no error
```

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_pots.py` — FAIL.
- [ ] **Step 3: Implement** the four functions in `app/pots.py`.
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** `feat: pot balances with hand-set anchors`

---

### Task 4: Internal transfer detection

**Files:**
- Create: `app/transfers.py`
- Modify: `app/importers/base.py` (`ParsedTransaction`), `app/importers/csv_banks.py` (`SparkasseCSV.parse`), `app/main.py` (`import_csv`), `app/gamify.py` (`monthly_cashflow`)
- Test: `tests/test_transfers.py` (create), `tests/test_importers.py`

**Interfaces:**
- Produces:
  - `ParsedTransaction.counterparty_iban: str = ""` (new last field).
  - `normalize_iban(s: str | None) -> str | None` — strip all whitespace, uppercase; returns `None` if empty or not matching the plausibility regex.
  - `is_plausible_iban(s: str) -> bool`.
  - `mark_transfers(conn) -> int` — recompute `is_transfer` for all rows (algorithm in the spec, "Transfers" steps 1–3); returns how many rows are marked.
  - `monthly_cashflow` skips rows with `is_transfer = 1`.

- [ ] **Step 1: Write failing tests**

```python
# importers: Sparkasse sample row with Kontonummer "DE11111111111111111111" -> counterparty_iban set;
assert normalize_iban("de12 3456 7890 1234 5678 90") == "DE12345678901234567890"   # Review Focus 2
assert normalize_iban("1234567") is None and normalize_iban("") is None            # Review Focus 1
# mark_transfers, two accounts A (iban IA) and B (iban IB):
#   A: -100 on 2026-11-05 with counterparty_iban IB  -> direct
#   B: +100 on 2026-11-07, no iban                   -> paired
#   B: +100 on 2026-11-20                             -> outside window, stays 0
#   A: -100 on 2026-11-06 to IB and B: +100 on 2026-11-06 -> pairs with the closest, each B row used once
assert marked == {...exact ids...}
# removing IB (UPDATE accounts SET iban=NULL) then mark_transfers() -> all 0
# cashflow: a marked pair contributes 0 income and 0 spend
```

API test in `tests/test_api.py`: import `sparkasse_sample.csv` into account A, create B with IBAN `DE11111111111111111111` via SQL, re-import → `/api/transactions` shows the salary rows `is_transfer == 1` and `/api/summary` income drops accordingly.

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_transfers.py tests/test_importers.py` — FAIL.
- [ ] **Step 3: Implement** `app/transfers.py`; Sparkasse parser fills `counterparty_iban=normalize_iban(r.get("Kontonummer"))  or ""`; `import_csv` stores `counterparty_iban` (NULL when empty) and calls `transfers.mark_transfers(conn)` before the imports row is written; `monthly_cashflow` adds `WHERE is_transfer = 0`. ING/BoS parsers unchanged.
- [ ] **Step 4: Run** full suite — PASS (existing dedup tests prove keys unchanged).
- [ ] **Step 5: Commit** `feat: detect transfers between own accounts by IBAN`

---

### Task 5: Plan summary in `/api/summary`

**Files:**
- Modify: `app/plan.py`, `app/gamify.py` (`summary`)
- Test: `tests/test_plan.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `occurrences`, `next_due` (Task 2), `account_pots` (Task 3), `monthly_cashflow` (Task 4).
- Produces:
  - `plan_summary(conn, today: date, cashflow: dict) -> dict` with keys `bills_this_month`, `saving_this_month`, `still_to_come`, `avg_income` (float|None), `left_after_plan` (float|None); all floats rounded 2 dp.
  - `upcoming(conn, today: date, days: int = 60, limit: int = 10) -> list[dict]` — keys `recurring_id`, `name`, `date` (ISO), `amount`, `kind` (`"bill"`|`"transfer"`), `to_account` (name|None), `to_pot` (name|None).
  - `summary()` adds top-level `plan`, `upcoming`; each account gains `iban`, `pots` (from `account_pots`), and `unassigned` (`balance − Σ pots`, only when it has pots, else `None`).

- [ ] **Step 1: Write failing tests** (today = 2026-11-12):

```python
# bill €600 yearly due 2026-11-20, bill €50 monthly due day 3, transfer €100 monthly due day 25
p = plan_summary(conn, date(2026,11,12), cashflow)
assert p["bills_this_month"] == 650.0 and p["saving_this_month"] == 100.0
assert p["still_to_come"] == 700.0                    # 600 (20th) + 100 (25th); the 3rd already passed
assert plan_summary(conn, date(2026,12,12), cashflow)["bills_this_month"] == 50.0   # yearly absent
# avg_income over Aug/Sep/Oct only (Nov in progress excluded); months without data skipped
assert p["avg_income"] == pytest.approx(...)
# Review Focus 5: empty DB
assert plan_summary(conn, d, {}) == {"bills_this_month": 0.0, "saving_this_month": 0.0,
    "still_to_come": 0.0, "avg_income": None, "left_after_plan": None}
assert [u["date"] for u in upcoming(conn, date(2026,11,12))][:3] == ["2026-11-20", "2026-11-25", "2026-12-03"]
```

API: `/api/summary` on an empty DB contains `plan` (as above), `upcoming == []`; an account with a pot shows `pots` and `unassigned`.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `plan_summary`, `upcoming`; wire into `gamify.summary` (pass `today` through; reuse the `cashflow` it already computes).
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** `feat: monthly plan and upcoming payments in summary`

---

### Task 6: API routes for IBAN, pots and recurring items

**Files:**
- Create: `app/routes_plan.py`
- Modify: `app/main.py` (`app.include_router(routes_plan.router)` before the static mount; `/api/transactions` already returns `t.*`, so `is_transfer` comes through)
- Test: `tests/test_api_plan.py` (create; reuse the `client` fixture by moving it to `tests/conftest.py`)

**Interfaces:**
- Consumes: `pots.*` (Task 3), `transfers.normalize_iban/is_plausible_iban/mark_transfers` (Task 4), `plan.next_due`, `plan.today` (Task 2).
- Produces the endpoints in the spec's API table. Pydantic models: `IbanIn{iban: str | None}`, `PotIn{name: str, balance: float = 0}`, `PotPatch{name: str | None, balance: float | None}`, `RecurringIn{name, amount: float, from_account_id: int, frequency: str, due_day: int, start_month: str, to_account_id: int | None = None, to_pot_id: int | None = None, active: bool = True}`, `RecurringPatch` = same fields all optional. `GET /api/recurring` rows include `next_due` (ISO or null).

- [ ] **Step 1: Write failing tests** — one per rule, asserting status codes:

```python
# PATCH iban: "de12 3456…" stored normalised (200); same IBAN on 2nd account -> 409; "abc" -> 400; null clears
# pots: create 201; duplicate name on same account -> 409; PATCH balance re-anchors; DELETE referenced -> 409
#   with both item names in detail; DELETE unreferenced -> 204
# recurring 400s: amount 0, amount -5, due_day 0, due_day 32, frequency "weekly", start_month "2026-13",
#   to_account_id == from_account_id, to_pot_id without to_account_id, pot of another account
# recurring 404s: unknown from_account_id / to_account_id / to_pot_id
# Review Focus 4: PATCH to_account_id to C while to_pot_id belongs to B -> 400
# PATCH amount on a pot-feeding item: monkeypatch plan.today; pot balance before == after on that day
# DELETE item -> 204, pot keeps its balance
```

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_api_plan.py` — FAIL.
- [ ] **Step 3: Implement** `app/routes_plan.py`. Validation lives in one `_validate(conn, merged: dict) -> None` raising `HTTPException`, used by POST and PATCH (PATCH merges the patch over the stored row first). Before PATCH/DELETE of an item, call `reanchor_pots(conn, {old.to_pot_id, new.to_pot_id}, plan.today())`. IBAN PATCH calls `mark_transfers`.
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** `feat: API for account IBANs, pots and regular payments`

---

### Task 7: Front end — tabs, Accounts tab, Plan card

**Files:**
- Create: `web/accounts.js`
- Modify: `web/index.html`, `web/app.js`, `web/app.css`, `web/sw.js` (add `/accounts.js` to `SHELL`, bump `CACHE` to `finance-hub-shell-v2`)

**Interfaces:**
- Consumes: endpoints from Tasks 5–6.
- Produces: `window.FH = { api, el, toast, money, refresh }` exported from `app.js` (plain script, loaded before `accounts.js`); `accounts.js` exposes `renderAccountsTab(summary, recurring)` called from `refresh()`.

- [ ] **Step 1: Markup** — wrap current overview cards in `<div id="tab-overview">`, add `<div id="tab-accounts" hidden>`, a `<nav class="tabbar">` with two buttons (`data-tab="overview"|"accounts"`, `aria-current` on the active one), a Plan card (`#plan`: four rows) and Upcoming card (`#upcoming`) on the overview, a `<dialog id="payment-dialog">` with the fields listed in the spec, and a `<dialog id="confirm-dialog">`. Change the payslip hint "Filed to your NAS by year" to "Filed to your NAS".
- [ ] **Step 2: Tabs** — show/hide by `location.hash` (`#accounts` → accounts, else overview); listen to `hashchange`.
- [ ] **Step 3: Overview** — Plan card shows the four values with `money()`, `null` → "—"; Upcoming rows "name · date · amount" plus "→ Account · Pot" for transfers; transactions with `is_transfer` show a "Transfer" badge and class `amt` without `pos/neg`.
- [ ] **Step 4: Accounts tab** (`web/accounts.js`) — per account card as in the spec: IBAN row (tap → inline input, Save calls `PATCH`), Set balance, Import CSV (reuse `wireDrop`), pots list with Set / Add pot (inline inputs, not `prompt()`), Unassigned with class `neg` when < 0, payments list (greyed when `active` false) and + Add payment.
- [ ] **Step 5: Payment dialog** — Pot `<select>` visible only when the chosen Transfer-to account has pots; amount input accepts a decimal comma (`"12,50"` → `12.5`); Pause/Resume toggles `active`; Delete opens `#confirm-dialog`; API errors show via `toast(msg, true)` and keep the dialog open.
- [ ] **Step 6: Verify** — `node --check web/app.js web/accounts.js`; run `uvicorn app.main:app --port 8092` with a temp `FINANCE_HUB_DB`, then in the browser: create Giro + Sparkonto, set IBANs, add pots Mine/Parents/Children, add a monthly transfer €100 → Children and a yearly €600 bill due this month; check Plan card numbers, Upcoming order, Unassigned turns red when pots exceed balance, delete-pot refusal message, reload keeps `#accounts`; import `sample_data/sparkasse_sample.csv` and see Transfer badges once a matching IBAN exists. Check at 375 px width and in dark mode.
- [ ] **Step 7: Commit** `feat: Accounts tab with pots and regular payments, Plan card on overview`

---

### Task 8: Docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** README "v0" list: add regular payments/pots/transfer detection; remove the "Internal transfers … not detected yet" note and roadmap item 1's transfer half; note that transfer detection needs each account's IBAN and works from Sparkasse exports today.
- [ ] **Step 2:** Full suite green; commit `docs: regular payments, pots and transfers`.

Deployment to the Pi is not part of this plan; it needs its own go-ahead.
