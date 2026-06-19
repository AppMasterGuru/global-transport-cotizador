"""
GT Cotizador — Uptime Watcher Daemon

Dedicated to one job: poll the public /health endpoint every 5 minutes and
alert Barney via Slack on outage/recovery. Deliberately separate from
scripts/monitor_daemon.py, which also checks the local SQLite DB, SharePoint,
and SMTP — those checks assume a filesystem shared with the Flask process.
This daemon is meant to run as its OWN Railway service (its own start
command), which gets its own ephemeral filesystem with no access to the
app's cotizador.db — so it must not depend on local DB state.

Deploy (same Railway project, separate service):
    1. Create a new service in the GT Cotizador Railway project, pointed at
       this same repo/branch.
    2. Override its start command to: python scripts/uptime_daemon.py
    3. Set APP_BASE_URL on that service to the PUBLIC app URL
       (https://global-transport-cotizador-production.up.railway.app),
       not localhost — this service has no local Flask process to call.
    4. Set SLACK_WEBHOOK_URL (same value as the main service) so alerts
       reach #gt-monitor instead of stub-logging to console.
    Known limitation: this service lives in the same Railway project as the
    app. A project-wide Railway outage silences the watcher along with the
    app it watches — accepted tradeoff for now (see uptime monitoring spec).

Usage (local):
    cd cotizador
    source .venv/bin/activate
    python scripts/uptime_daemon.py

Stops cleanly on Ctrl-C or SIGTERM (logs UPTIME_WATCHER_STOPPED to audit).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Path setup ─────────────────────────────────────────────────────────────────
# scripts/ lives one level inside cotizador/ — resolve the project root so
# imports and .env loading work regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # cotizador/ project root
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env before importing core modules (they read env vars at import time)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass  # python-dotenv not installed — rely on shell env

from core.db import audit, init_db  # noqa: E402
from core.monitor import (  # noqa: E402
    UptimeWatcher,
    check_flask_health,
    get_railway_log_tail,
)
from core.slack_alerter import send_recovery_alert, send_uptime_down_alert  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [uptime] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("uptime_daemon")

# ── Constants ─────────────────────────────────────────────────────────────────

UPTIME_INTERVAL_S = int(os.getenv("UPTIME_CHECK_INTERVAL_S", "300"))  # 5 min


# ══════════════════════════════════════════════════════════════════════════════
# Alert callbacks
# ══════════════════════════════════════════════════════════════════════════════

def _on_down(result: dict, consecutive_failures: int) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    log_lines = get_railway_log_tail(20)
    log.warning(
        "OUTAGE detected — %d consecutive failures. error=%s",
        consecutive_failures, result.get("error"),
    )
    send_uptime_down_alert(
        consecutive_failures=consecutive_failures,
        last_error=result.get("error") or "unknown",
        timestamp_utc=ts,
        log_lines=log_lines,
    )
    audit("UPTIME_OUTAGE_DETECTED", None, "uptime_daemon", {
        "consecutive_failures": consecutive_failures,
        "error": result.get("error"),
        "ts": ts,
        "logs_included": log_lines is not None,
    })


def _on_recovery(result: dict) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    log.info("RECOVERY — /health is ok again.")
    send_recovery_alert("GT Cotizador /health", f"/health recovered at {ts} UTC.")
    audit("UPTIME_RECOVERY", None, "uptime_daemon", {"ts": ts})


def build_watcher() -> UptimeWatcher:
    return UptimeWatcher(
        check_fn=check_flask_health,
        on_down=_on_down,
        on_recovery=_on_recovery,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Healthcheck server — Railway requires an HTTP healthcheck on every service;
# this daemon has no web app of its own, so it serves a trivial /health here.
# Runs in a background thread so it never blocks the polling loop.
# ══════════════════════════════════════════════════════════════════════════════

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # silence default BaseHTTPRequestHandler stderr access logging


def start_health_server(port: int) -> HTTPServer:
    """Start the /health HTTP server on a background daemon thread. Returns the server (caller may call .shutdown())."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ══════════════════════════════════════════════════════════════════════════════
# Daemon
# ══════════════════════════════════════════════════════════════════════════════

class UptimeDaemon:
    def __init__(self) -> None:
        self._running = True
        self._watcher = build_watcher()
        self._last_check_ts = 0.0
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        log.info("Signal %s received — shutting down.", signum)
        self._running = False

    def run(self) -> None:
        init_db()

        port = int(os.getenv("PORT", "8080"))
        start_health_server(port)
        log.info("Health server listening on :%d.", port)

        audit("UPTIME_WATCHER_STARTED", None, "uptime_daemon", {
            "interval_s": UPTIME_INTERVAL_S,
            "health_server_port": port,
        })
        log.info("Uptime watcher started. Checking /health every %ds.", UPTIME_INTERVAL_S)

        self._watcher.poll()
        self._last_check_ts = time.monotonic()

        while self._running:
            now = time.monotonic()
            if now - self._last_check_ts >= UPTIME_INTERVAL_S:
                try:
                    self._watcher.poll()
                except Exception as exc:
                    log.error("Uptime poll error: %s", exc)
                self._last_check_ts = time.monotonic()
            time.sleep(10)  # Tick every 10s (precise enough for 5-min interval)

        audit("UPTIME_WATCHER_STOPPED", None, "uptime_daemon", {
            "reason": "signal", "ts": datetime.now(timezone.utc).isoformat(),
        })
        log.info("Uptime watcher stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    UptimeDaemon().run()
