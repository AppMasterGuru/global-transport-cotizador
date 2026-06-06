# GT Cotizador — Startup Guide

## Normal startup (two terminals)

**Terminal 1 — Flask app:**
```bash
cd cotizador
PYTHONPATH=. APP_ENV=development python3 -m flask --app api.app run --port 8080
```
Flask runs at: http://127.0.0.1:8080

> Use this exact command — `python3 -m flask` avoids PATH issues where the system flask binary is picked up instead of the venv one. `APP_ENV=development` enables /demo-reset.

**Terminal 2 — Monitor daemon:**
```bash
cd cotizador
source .venv/bin/activate
python monitor_daemon.py
```
The daemon runs alongside Flask. It checks Flask health every 5 minutes, detects audit anomalies every 15 minutes, and sends a daily digest to Slack at 8:00 AM Lima time.

---

## Demo startup (clean slate)

```bash
# 1. Start Flask in dev mode (enables /demo-reset)
cd cotizador
source .venv/bin/activate
APP_ENV=development flask --app api.app run --debug

# 2. Clear all test data before demo
open "http://127.0.0.1:5000/demo-reset?password=gt2026"

# 3. Start monitor in a second terminal (optional — shows system is live)
APP_ENV=development python monitor_daemon.py
```

---

## First-time setup

```bash
cd cotizador
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with real credentials
flask --app api.app run
```

---

## Environment variables

See `.env.example` for all variables with comments.

Key vars to fill before demo:
| Variable | Required for | Status |
|---|---|---|
| `GRAPH_ACCESS_TOKEN` | Live rate cards from SharePoint | Blocked — admin consent pending |
| `SHAREPOINT_DRIVE_ID` | Live rate cards | Blocked — need after admin consent |
| `TARIFAS_FOLDER_ID` | Live rate cards | Blocked — need after admin consent |
| `GT_EMAIL_ADDRESS` + `GT_EMAIL_PASSWORD` | Real email sending | Blocked — Vania pending |
| `SLACK_WEBHOOK_URL` | Slack monitoring alerts | Ready to configure anytime |
| `ANTHROPIC_API_KEY` | Claude API parsing (email listener) | Optional for demo — stub works |

---

## Key URLs

| URL | What it is |
|---|---|
| http://127.0.0.1:5000 | Dashboard |
| http://127.0.0.1:5000/quote/new | New quote form |
| http://127.0.0.1:5000/audit | Audit log |
| http://127.0.0.1:5000/acknowledgment/demo | Multilingual ack demo |
| http://127.0.0.1:5000/email-listener/preview | Email listener preview |
| http://127.0.0.1:5000/monitor | Internal monitoring dashboard |
| http://127.0.0.1:5000/wca-pilot | WCA campaign generator |
| http://127.0.0.1:5000/demo-reset?password=gt2026 | Reset demo data (dev only) |
| http://127.0.0.1:5000/health | Health check JSON |

---

## Running tests

```bash
cd cotizador
source .venv/bin/activate
pytest tests/ -v
```
Expected: 78 tests passing (as of 2026-05-14).

---

## Stopping the daemon

Press `Ctrl-C` — the daemon catches SIGINT, logs `MONITOR_STOPPED` to the audit trail, and exits cleanly.
