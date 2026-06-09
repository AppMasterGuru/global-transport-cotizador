"""
GT Cotizador — Monitoring Daemon

Runs as a separate process alongside the Flask app.

Usage:
    cd cotizador
    source .venv/bin/activate
    python scripts/monitor_daemon.py

Stops cleanly on Ctrl-C or SIGTERM (logs MONITOR_STOPPED to audit).
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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
    attempt_flask_restart,
    check_audit_anomalies,
    clear_stale_cache,
    generate_daily_digest,
    run_health_checks,
)
from core.slack_alerter import (  # noqa: E402
    send_alert,
    send_anomaly_alert,
    send_daily_digest,
    send_health_alert,
    send_recovery_alert,
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [monitor] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("monitor_daemon")

# ── Constants ─────────────────────────────────────────────────────────────────

HEALTH_INTERVAL_S    = int(os.getenv("HEALTH_CHECK_INTERVAL_S", "300"))   # 5 min
ANOMALY_INTERVAL_S   = int(os.getenv("ANOMALY_CHECK_INTERVAL_S", "900"))  # 15 min
HEARTBEAT_INTERVAL_S = 1800                                                 # 30 min
DAILY_DIGEST_HOUR    = 8                                                    # 8:00 AM Lima
HEALTH_HISTORY_MAX   = 288                                                  # 24h × 12 checks/h

_LIMA_TZ = ZoneInfo("America/Lima")


# ══════════════════════════════════════════════════════════════════════════════
# Daemon class
# ══════════════════════════════════════════════════════════════════════════════

class MonitorDaemon:
    def __init__(self) -> None:
        self._running           = True
        self._last_health       = {}          # Most recent health report
        self._health_history:   list[dict] = []
        self._last_anomaly_ts   = 0.0
        self._last_health_ts    = 0.0
        self._last_heartbeat_ts = 0.0
        self._digest_sent_date  = None        # Date string of last digest (YYYY-MM-DD)

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT,  self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        log.info("Signal %s received — shutting down.", signum)
        self._running = False

    # ── Health check cycle ────────────────────────────────────────────────────

    def _do_health_check(self) -> None:
        log.info("Running health checks…")
        report = run_health_checks()
        overall = report.get("overall", "healthy")
        log.info("Health: %s (Flask=%s, DB=%s, SP=%s, SMTP=%s)",
                 overall,
                 report.get("flask", {}).get("status"),
                 report.get("database", {}).get("status"),
                 report.get("sharepoint", {}).get("status"),
                 report.get("smtp", {}).get("status"))

        # Recovery alert: previous bad → now good
        prev_overall = self._last_health.get("overall", "healthy")
        if prev_overall in ("degraded", "critical") and overall == "healthy":
            send_recovery_alert("GT Cotizador", "All systems back to healthy.")
            log.info("Recovery alert sent.")

        # Degraded or critical → alert Barney
        if overall in ("degraded", "critical"):
            send_health_alert(report)
            # Attempt Flask restart in dev only
            if report.get("flask", {}).get("status") == "down":
                attempted = attempt_flask_restart()
                if attempted:
                    log.info("Flask restart attempted (dev mode).")

        # Track history for uptime calculation
        self._health_history.append({
            "ts":      report["timestamp"],
            "overall": overall,
        })
        if len(self._health_history) > HEALTH_HISTORY_MAX:
            self._health_history.pop(0)

        self._last_health = report
        self._last_health_ts = time.monotonic()

    # ── Anomaly check cycle ───────────────────────────────────────────────────

    def _do_anomaly_check(self) -> None:
        log.info("Running anomaly detection…")
        anomalies = check_audit_anomalies()
        if anomalies:
            log.warning("%d anomal%s detected.", len(anomalies),
                        "y" if len(anomalies) == 1 else "ies")
            for anomaly in anomalies:
                send_anomaly_alert(anomaly)
        else:
            log.info("No anomalies detected.")

        clear_stale_cache()
        self._last_anomaly_ts = time.monotonic()

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def _do_heartbeat(self) -> None:
        healthy_count = sum(
            1 for h in self._health_history if h["overall"] == "healthy"
        )
        total = len(self._health_history) or 1
        uptime_pct = round(100.0 * healthy_count / total, 1)
        audit("MONITOR_HEARTBEAT", None, "monitor",
              {"uptime_pct": uptime_pct, "checks_tracked": total})
        log.info("Heartbeat — uptime %.1f%% (%d checks tracked).", uptime_pct, total)
        self._last_heartbeat_ts = time.monotonic()

    # ── Daily digest ─────────────────────────────────────────────────────────

    def _maybe_send_daily_digest(self) -> None:
        lima_now  = datetime.now(_LIMA_TZ)
        today_str = lima_now.strftime("%Y-%m-%d")
        if lima_now.hour == DAILY_DIGEST_HOUR and self._digest_sent_date != today_str:
            log.info("Generating daily digest…")
            digest = generate_daily_digest()
            # Inject uptime from history
            healthy_count = sum(1 for h in self._health_history if h["overall"] == "healthy")
            total = len(self._health_history) or 1
            digest["uptime_pct"] = round(100.0 * healthy_count / total, 1)
            send_daily_digest(digest)
            self._digest_sent_date = today_str
            log.info("Daily digest sent.")

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        # Startup
        init_db()
        audit("MONITOR_STARTED", None, "monitor", {
            "health_interval_s":  HEALTH_INTERVAL_S,
            "anomaly_interval_s": ANOMALY_INTERVAL_S,
            "version":            "1.0",
        })
        log.info("Monitor daemon started. Health every %ds, anomaly every %ds.",
                 HEALTH_INTERVAL_S, ANOMALY_INTERVAL_S)

        # Immediate startup health check
        self._do_health_check()
        startup_overall = self._last_health.get("overall", "healthy")
        if startup_overall == "healthy":
            send_alert("info", "GT Cotizador Monitor started",
                       "All systems nominal. Monitoring active.", {
                           "Health check interval": f"{HEALTH_INTERVAL_S}s",
                           "Anomaly check interval": f"{ANOMALY_INTERVAL_S}s",
                       })
        else:
            send_health_alert(self._last_health)

        self._last_anomaly_ts    = time.monotonic()
        self._last_heartbeat_ts  = time.monotonic()

        while self._running:
            now = time.monotonic()

            # Health check
            if now - self._last_health_ts >= HEALTH_INTERVAL_S:
                try:
                    self._do_health_check()
                except Exception as exc:
                    log.error("Health check error: %s", exc)

            # Anomaly check + cache clear
            if now - self._last_anomaly_ts >= ANOMALY_INTERVAL_S:
                try:
                    self._do_anomaly_check()
                except Exception as exc:
                    log.error("Anomaly check error: %s", exc)

            # Heartbeat
            if now - self._last_heartbeat_ts >= HEARTBEAT_INTERVAL_S:
                try:
                    self._do_heartbeat()
                except Exception as exc:
                    log.error("Heartbeat error: %s", exc)

            # Daily digest
            try:
                self._maybe_send_daily_digest()
            except Exception as exc:
                log.error("Daily digest error: %s", exc)

            time.sleep(10)  # Tick every 10s (precise enough for 5-min interval)

        # Graceful shutdown
        audit("MONITOR_STOPPED", None, "monitor",
              {"reason": "signal", "ts": datetime.now(timezone.utc).isoformat()})
        send_alert("info", "GT Cotizador Monitor stopped", "Daemon shut down cleanly.")
        log.info("Monitor daemon stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    MonitorDaemon().run()
