# Regular payments, pots and internal transfers — design

Date: 2026-11-12 · Status: draft for review

## Goal

Give a truthful "where am I right now" view of the money:

1. A **planning view** of regular payments (bills and savings transfers) per account.
2. **Pots** inside an account (e.g. the Sparkasse savings account split into Mine / Parents / Children).
3. **Internal transfers** between own accounts no longer count as income or spending.

Every amount counts in full on its due date. Nothing is spread over months:
a yearly €600 car insurance is €600 in the month it is due and €0 otherwise.

## Context

- Accounts: Sparkasse Giro (everyday, most bills), Sparkasse savings (pots), ING (savings),
  Bank of Scotland Germany (savings). All EUR.
- Data comes from manual CSV imports today. Matching planned payments against real
  transactions ("bill checklist") is **out of scope** until live bank data exists.

## Data model

All changes are additive. On startup, `db.init()` creates the new tables and adds the new
columns to existing databases (checked via `PRAGMA table_info`), so no data is lost.

### `accounts` (changed)

| column | type | notes |
|---|---|---|
| `iban` | TEXT NULL | Stored normalised: uppercase, no spaces. Unique when set (partial unique index). |

### `pots` (new)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `account_id` | INTEGER FK → accounts | |
| `name` | TEXT | Unique per account. |
| `anchor_balance` | REAL | Balance set by hand. |
| `anchor_date` | TEXT (ISO date) | Day the anchor was set. The anchor is the balance at the **end** of that day. |

### `recurring` (new)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | |
| `amount` | REAL | EUR, > 0. Always a payment out of `from_account_id`. |
| `from_account_id` | INTEGER FK → accounts | |
| `frequency` | TEXT | `monthly` \| `quarterly` \| `yearly` |
| `due_day` | INTEGER | 1–31. Clamped to the last day of shorter months. |
| `start_month` | TEXT | `YYYY-MM`. First due month; quarterly/yearly repeat every 3/12 months from here. |
| `to_account_id` | INTEGER NULL FK → accounts | Set ⇒ the item is a **transfer**, otherwise a **bill**. Must differ from `from_account_id`. |
| `to_pot_id` | INTEGER NULL FK → pots | Only with `to_account_id`; the pot must belong to that account. |
| `active` | INTEGER | 1 = active, 0 = paused. |

### `transactions` (changed)

| column | type | notes |
|---|---|---|
| `counterparty_iban` | TEXT NULL | Normalised. Not part of the dedup key, so existing keys stay stable. |
| `is_transfer` | INTEGER | 0/1, computed (see Transfers). |

## Due dates (`app/plan.py`, pure functions)

`occurrences(item, after, until)` yields due dates `d` with `after < d <= until`:
due months are `start_month + k × step` for `k ≥ 0` (step 1/3/12), day `min(due_day, last day of month)`.
Paused items yield nothing.

## Pots

- **Balance** = `anchor_balance` + sum of amounts of active transfer items with `to_pot_id = pot`
  over `occurrences(item, after=anchor_date, until=today)`.
- **Set by hand** (`PATCH /api/pots/{id}` with `balance`): `anchor_balance = balance`, `anchor_date = today`.
- **Re-anchoring on plan changes:** before an item that feeds a pot is edited, paused, resumed,
  deleted or pointed at a different pot, every affected pot is re-anchored to its current
  balance (anchor = today). Past contributions are kept; the change only affects the future.
- **Unassigned** for an account with pots = account balance − sum of its pot balances.
  Negative is allowed and shown in red. Money arriving without a pot (a transfer item with
  no `to_pot_id`, interest, one-off deposits) therefore lands in Unassigned automatically.
- Deleting a pot that a recurring item still points to is **refused (409)**, naming those items.

## Transfers (`app/transfers.py`)

- Importers fill `ParsedTransaction.counterparty_iban` where the export has it:
  Sparkasse `Kontonummer` column. ING and Bank of Scotland: only if a real export contains a
  counterparty IBAN column (to be verified against real files; otherwise left empty).
- `mark_transfers(conn)` recomputes `is_transfer` for **all** transactions, deterministically:
  1. Reset all to 0.
  2. **Direct:** a transaction whose `counterparty_iban` equals another own account's IBAN → 1.
  3. **Pairing:** for each direct transfer (ordered by date, id), find on the target account the
     unmarked transaction with amount `= −amount` and booking date within ±3 days,
     closest date first, then lowest id → 1.
- Runs after every CSV import and after any IBAN change.
- `monthly_cashflow` ignores transactions with `is_transfer = 1`. Net worth is unchanged.

## Plan summary (current calendar month)

From occurrences in the current month (`after` = last day of previous month, `until` = month end), full amounts:

- `bills_this_month` — items without `to_account_id`.
- `saving_this_month` — transfer items.
- `still_to_come` — the part of the two above with due date > today.
- `avg_income` — mean income of the last 3 **completed** months that have data, transfers
  excluded; `null` if there is none.
- `left_after_plan` — `avg_income − bills_this_month − saving_this_month`; `null` if `avg_income` is null.
- `upcoming` — occurrences from today (inclusive) through the next 60 days, max 10, sorted by date:
  name, date, amount, kind (bill/transfer), target account/pot name.

Unchanged on purpose: budget ring (`MONTHLY_BUDGET_EUR`), XP, streaks.

## API

| method & path | body | notes |
|---|---|---|
| `PATCH /api/accounts/{id}` | `{iban}` (null clears) | 409 if used by another account; re-runs `mark_transfers`. |
| `POST /api/accounts/{id}/pots` | `{name, balance}` | anchor = today. |
| `PATCH /api/pots/{id}` | `{name?, balance?}` | `balance` re-anchors. |
| `DELETE /api/pots/{id}` | | 409 if referenced. |
| `GET /api/recurring` | | All items with next due date. |
| `POST /api/recurring` | item fields | 201. |
| `PATCH /api/recurring/{id}` | any item fields | Re-anchors affected pots first. |
| `DELETE /api/recurring/{id}` | | Re-anchors affected pots first. |
| `GET /api/summary` | | Adds `plan`, `upcoming`, and per account `iban`, `pots[]`, `unassigned`. |
| `GET /api/transactions` | | Adds `is_transfer`. |

**Validation (400 with a clear message):** amount ≤ 0; `due_day` outside 1–31; bad `frequency`
or `start_month`; `to_account_id = from_account_id`; `to_pot_id` without `to_account_id`
or not belonging to it; unknown account/pot ids (404); malformed IBAN (basic shape check).

New routes live in `app/routes_plan.py` (FastAPI `APIRouter`) so `main.py` doesn't grow further.

## Front end

- Bottom **tab bar**: Overview · Accounts. Selected tab kept in the URL hash (`#accounts`).
- **Overview**: as today, plus a **Plan** card (bills this month, saving this month, still to come,
  left after plan) and an **Upcoming** list. Transfers in the recent-transactions list are
  marked "Transfer" and shown neutral (not red/green).
- **Accounts**: one card per account:
  - Header: name, bank, balance, IBAN (tap to add/edit), Set balance, Import CSV (drop still works).
  - Pots (if any): name + balance + Set; **Unassigned** (red if negative); + Add pot.
  - Regular payments: name, amount, frequency, next due date; transfers show "→ Account · Pot";
    paused items greyed; + Add payment.
- **Payment dialog** (add/edit): name, amount, frequency, due day, start month,
  Transfer to (optional), Pot (shown only if the chosen account has pots). Edit adds
  Pause/Resume and Delete; delete confirms inside the dialog (no browser `confirm()`).
- New code in `web/accounts.js`; `web/app.js` keeps the overview. Same `el()` DOM helper, no innerHTML.

## Testing (written first)

- `occurrences`: month-end clamping (31st in Feb, leap year), quarterly/yearly cycles,
  start month in the future, paused items.
- Pot balance: anchor + transfers since; same-day anchor excludes that day's due item;
  set by hand; re-anchoring when an item is edited/paused/deleted keeps past contributions.
- Transfers: direct IBAN match, pairing (±3 days, closest first, no double pairing),
  recompute after adding/removing an IBAN, excluded from cashflow/savings rate.
- Plan summary: full amounts in due month only (yearly item absent in other months),
  still-to-come split by today, avg income over completed months, null when no data.
- API: every validation rule above, pot delete refused when referenced, migration of an
  existing v0 database (new columns appear, rows intact).

## Out of scope

Matching planned payments to real transactions, regular payments **out of** a pot
(a withdrawal is handled by setting the pot balance by hand), changing the budget ring/XP/streaks,
the Bank of Scotland Germany CSV importer (waiting for a real export), live bank sync.
