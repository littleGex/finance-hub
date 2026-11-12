# finance-hub

Self-hosted, gamified personal finance dashboard for Sparkasse, ING and Bank of Scotland.
Runs on the Raspberry Pi, files payslips to the NAS, nothing leaves your network.

## v0: manual first

- Drop a CSV export on an account to import it (re-importing is safe; duplicates are skipped).
- Drop a payslip PDF; it is read and filed to `PAYSLIP_DIR/<year>/`. Unreadable ones are flagged "Review".
- Net worth, activity rings (savings rate, budget, data freshness), saving streak, XP and levels.
- Everything is EUR (Sparkasse, ING and Bank of Scotland Germany).

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit
uvicorn app.main:app --port 8092 --reload
```

Open http://localhost:8092, add an account, then try the files in `sample_data/`.
Add to Home Screen on iPhone for the app-like experience.

Docker (Pi): `docker compose up -d --build`, then open `http://<pi>:8094`. In `.env` set:

- `HOST_PORT` (default 8094; 8092 is taken on the Pi by steuer-hub; check free ports with `ss -tln`)
- `ALLOWED_HOSTS` to the names/IPs you open the app with, e.g. `ford-home-pi.local,192.168.2.52`
- `NAS_PAYSLIP_PATH` to the mounted NAS payslip folder and `PAYSLIP_LAYOUT=month` to file into the existing `Jan/ … Dec/` folders

## Test

```bash
pytest
```

## Important notes

- **No login.** Keep it on your home network only. Do not expose it to the internet, and do not add it to nginx-proxy-manager or the cloudflared tunnel. Requests with an unknown Host or a foreign Origin are rejected. If you want access away from home, put it behind a VPN (e.g. WireGuard/Tailscale).
- **Check the CSV parsers against real exports.** `app/importers/csv_banks.py` follows the typical layouts; banks change formats. Adjust column names there if an import is rejected.
- **Payslip parsing is best effort** (`app/payslip.py`). Layouts vary by employer; send a sample (redacted) to tune the patterns.
- Internal transfers between your own accounts are not detected yet, so they count as income/spend in the rings.
- Back up `data/` (the SQLite DB and archived exports).

## Roadmap

1. Categories + rules, internal-transfer detection
2. Live Sparkasse/ING sync via FinTS (the importer interface in `app/importers/base.py` is the seam)
3. Optional paid aggregator for Bank of Scotland, if worth the cost
4. Goals (savings pots), achievements/badges, monthly "wrapped" recap
5. Auth (PIN/passkey) before any remote access

## Layout

```
app/            FastAPI backend (db, importers, payslip, gamify)
web/            Static PWA (vanilla JS, animated SVG rings)
sample_data/    Fake exports for each bank
tests/
```
