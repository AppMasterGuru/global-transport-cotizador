"""
GT Cotizador — Health monitoring and anomaly detection engine.

Run via monitor_daemon.py (separate process alongside Flask).
All checks are safe to call from Flask routes too (for /monitor dashboard).

Health checks:       check_flask_health, check_database_health,
                     check_sharepoint_health, check_smtp_health, run_health_checks
Anomaly detection:   check_audit_anomalies
Auto-recovery:       attempt_flask_restart, clear_stale_cache
Daily digest:        generate_daily_digest
"""

from __future__ import annotations

import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests as _requests

from core.db import audit, get_connection

# ── Config ────────────────────────────────────────────────────────────────────

_FLASK_URL     = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")
_HEALTH_URL    = f"{_FLASK_URL}/health"
_APP_ENV       = os.getenv("APP_ENV", "production")
_CACHE_DIR     = Path(os.getenv("CACHE_DIR", "/tmp/gt_cotizador_cache"))
_LIMA_TZ       = ZoneInfo("America/Lima")

_SMTP_SERVER   = os.getenv("GT_SMTP_SERVER", "")
_SMTP_PORT     = int(os.getenv("GT_SMTP_PORT", "587"))
_SMTP_ADDRESS  = os.getenv("GT_EMAIL_ADDRESS", "")


# ══════════════════════════════════════════════════════════════════════════════
# Health checks
# ══════════════════════════════════════════════════════════════════════════════

def check_flask_health() -> dict:
    """
    HTTP GET /health on the running Flask app.
    Treats anything other than HTTP 200 with body {"status": "ok"} as down
    (non-200, timeout/exception, or an unexpected/missing body).
    Returns {status, response_time_ms, error}.
    """
    start = time.monotonic()
    try:
        resp = _requests.get(_HEALTH_URL, timeout=10)
        elapsed_ms = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("status") == "ok":
                return {"status": "ok", "response_time_ms": round(elapsed_ms, 1), "error": None}
            return {
                "status": "down",
                "response_time_ms": round(elapsed_ms, 1),
                "error": f"unexpected body: {body!r}",
            }
        return {
            "status": "down",
            "response_time_ms": round(elapsed_ms, 1),
            "error": f"HTTP {resp.status_code}",
        }
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "status": "down",
            "response_time_ms": round(elapsed_ms, 1),
            "error": str(exc),
        }


def check_database_health() -> dict:
    """
    Opens cotizador.db, runs a COUNT query.
    Returns {status, quote_count, error}.
    """
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()
        return {"status": "ok", "quote_count": row[0], "error": None}
    except Exception as exc:
        return {"status": "down", "quote_count": 0, "error": str(exc)}


def check_sharepoint_health() -> dict:
    """
    Attempts Graph API call to list the TARIFAS folder.
    Returns {status, error} — status: ok | down | not_configured.
    """
    # Import here so that drive._CONFIGURED reflects the live env at call time
    try:
        from core.drive import _CONFIGURED, list_tarifas_folder  # noqa: PLC0415
    except ImportError as exc:
        return {"status": "down", "error": f"drive.py import failed: {exc}"}

    if not _CONFIGURED:
        return {"status": "not_configured", "error": None}

    try:
        items = list_tarifas_folder()
        if items is None:
            return {"status": "down", "error": "list_tarifas_folder returned None"}
        return {"status": "ok", "file_count": len(items), "error": None}
    except Exception as exc:
        return {"status": "down", "error": str(exc)}


def check_smtp_health() -> dict:
    """
    Attempts SMTP connection (no auth, no send).
    Returns {status, error} — status: ok | down | not_configured.
    """
    if not (_SMTP_SERVER and _SMTP_ADDRESS):
        return {"status": "not_configured", "error": None}

    try:
        with smtplib.SMTP(_SMTP_SERVER, _SMTP_PORT, timeout=5) as smtp:
            smtp.ehlo()
        return {"status": "ok", "error": None}
    except Exception as exc:
        return {"status": "down", "error": str(exc)}


def run_health_checks() -> dict:
    """
    Runs all four health checks and computes an overall status.

    Overall status:
      healthy   — all configured services ok
      degraded  — one non-critical service down (SharePoint or SMTP)
      critical  — Flask or DB down

    Returns full report dict with timestamp.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    now_lima = datetime.now(_LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S Lima")

    flask_h   = check_flask_health()
    db_h      = check_database_health()
    sp_h      = check_sharepoint_health()
    smtp_h    = check_smtp_health()

    flask_ok  = flask_h["status"] == "ok"
    db_ok     = db_h["status"] == "ok"
    sp_ok     = sp_h["status"] in ("ok", "not_configured")
    smtp_ok   = smtp_h["status"] in ("ok", "not_configured")

    if not flask_ok or not db_ok:
        overall = "critical"
    elif not sp_ok or not smtp_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "overall":     overall,
        "timestamp":   now_iso,
        "timestamp_lima": now_lima,
        "flask":       flask_h,
        "database":    db_h,
        "sharepoint":  sp_h,
        "smtp":        smtp_h,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Anomaly detection
# ══════════════════════════════════════════════════════════════════════════════

def check_audit_anomalies() -> list[dict]:
    """
    Reads audit_log for the last 60 minutes and flags anomalies.

    Checks:
      1. QUOTE_PARSE_FAILED spike  — >3 in 60 min
      2. ACK_SEND_FAILED spike     — >3 in 60 min
      3. Stuck PENDING quotes      — >5 quotes PENDING for >2 hours
      4. No activity               — 0 events in 4 hours (business hours 8am-8pm Lima)

    Returns list of {type, severity, count, message} dicts.
    """
    anomalies: list[dict] = []
    now_utc = datetime.now(timezone.utc)
    cutoff_60m  = (now_utc - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_4h   = (now_utc - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_2h   = (now_utc - timedelta(hours=2)).isoformat()

    try:
        with get_connection() as conn:
            # 1. QUOTE_PARSE_FAILED spike
            row = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE event_type = 'QUOTE_PARSE_FAILED' AND ts >= ?",
                (cutoff_60m,),
            ).fetchone()
            if row and row[0] > 3:
                anomalies.append({
                    "type":     "QUOTE_PARSE_FAILED_SPIKE",
                    "severity": "warning",
                    "count":    row[0],
                    "message":  f"{row[0]} quote parse failures in the last 60 minutes.",
                })

            # 2. ACK_SEND_FAILED spike
            row = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE event_type = 'ACK_SEND_FAILED' AND ts >= ?",
                (cutoff_60m,),
            ).fetchone()
            if row and row[0] > 3:
                anomalies.append({
                    "type":     "ACK_SEND_FAILED_SPIKE",
                    "severity": "warning",
                    "count":    row[0],
                    "message":  f"{row[0]} acknowledgment send failures in the last 60 minutes.",
                })

            # 3. Stuck PENDING quotes (>2 hours old)
            row = conn.execute(
                "SELECT COUNT(*) FROM quotes "
                "WHERE status = 'PENDING' AND created_at <= ?",
                (cutoff_2h,),
            ).fetchone()
            if row and row[0] > 5:
                anomalies.append({
                    "type":     "STUCK_PENDING_QUOTES",
                    "severity": "warning",
                    "count":    row[0],
                    "message":  f"{row[0]} quotes have been PENDING for more than 2 hours.",
                })

            # 4. No activity during business hours (8am–8pm Lima)
            lima_hour = datetime.now(_LIMA_TZ).hour
            if 8 <= lima_hour < 20:
                row = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE ts >= ?",
                    (cutoff_4h,),
                ).fetchone()
                if row and row[0] == 0:
                    anomalies.append({
                        "type":     "NO_ACTIVITY",
                        "severity": "warning",
                        "count":    0,
                        "message":  "Zero audit events in the last 4 hours during business hours.",
                    })

    except Exception as exc:
        anomalies.append({
            "type":     "ANOMALY_CHECK_FAILED",
            "severity": "critical",
            "count":    0,
            "message":  f"Anomaly detection failed: {exc}",
        })

    return anomalies


# ══════════════════════════════════════════════════════════════════════════════
# Auto-recovery
# ══════════════════════════════════════════════════════════════════════════════

def attempt_flask_restart() -> bool:
    """
    DEV ONLY — attempts to signal Flask to restart.
    Only runs when APP_ENV=development.
    Logs MONITOR_FLASK_RESTART_ATTEMPTED to audit.
    Returns True if restart was attempted.
    """
    if _APP_ENV != "development":
        return False

    audit(
        "MONITOR_FLASK_RESTART_ATTEMPTED",
        None,
        "monitor",
        {"app_env": _APP_ENV, "note": "Manual intervention may be required in production."},
    )
    return True


def clear_stale_cache() -> bool:
    """
    Deletes cache files older than 25 hours from CACHE_DIR.
    Logs MONITOR_CACHE_CLEARED to audit if any files removed.
    Returns True if any files were cleared.
    """
    if not _CACHE_DIR.exists():
        return False

    cutoff = time.time() - (25 * 3600)
    cleared: list[str] = []

    try:
        for f in _CACHE_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                cleared.append(f.name)
    except OSError:
        return False

    if cleared:
        audit(
            "MONITOR_CACHE_CLEARED",
            None,
            "monitor",
            {"files_cleared": len(cleared), "filenames": cleared[:10]},
        )
        return True

    return False


# ══════════════════════════════════════════════════════════════════════════════
# Daily digest
# ══════════════════════════════════════════════════════════════════════════════

def generate_daily_digest() -> dict:
    """
    Reads the last 24 hours of audit_log and summarises activity.

    Returns:
        {
            quotes_generated, quotes_approved, quotes_sent, acks_sent,
            errors, uptime_pct (placeholder), top_issues, period_hours,
        }
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    digest: dict = {
        "quotes_generated": 0,
        "quotes_approved":  0,
        "quotes_sent":      0,
        "acks_sent":        0,
        "errors":           [],
        "uptime_pct":       100.0,   # Filled by daemon from health_check_history
        "top_issues":       [],
        "period_hours":     24,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }

    _ERROR_EVENT_TYPES = {
        "QUOTE_PARSE_FAILED", "ACK_SEND_FAILED", "QUOTE_SEND_FAILED",
        "RATE_CARD_FALLBACK", "ANOMALY_CHECK_FAILED",
    }

    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT event_type, detail_json FROM audit_log WHERE ts >= ? ORDER BY ts ASC",
                (cutoff,),
            ).fetchall()

        error_counts: dict[str, int] = {}
        for row in rows:
            et = row["event_type"]
            if et == "ARTIFACT_GENERATED":
                digest["quotes_generated"] += 1
            elif et == "STATUS_TRANSITION":
                import json  # noqa: PLC0415
                detail = {}
                try:
                    detail = json.loads(row["detail_json"] or "{}")
                except Exception:
                    pass
                if detail.get("to") == "APPROVED":
                    digest["quotes_approved"] += 1
                elif detail.get("to") == "SENT":
                    digest["quotes_sent"] += 1
            elif et == "ACK_SENT":
                digest["acks_sent"] += 1
            elif et in _ERROR_EVENT_TYPES:
                digest["errors"].append({"event_type": et, "detail": row["detail_json"]})
                error_counts[et] = error_counts.get(et, 0) + 1

        digest["top_issues"] = sorted(
            [{"type": k, "count": v} for k, v in error_counts.items()],
            key=lambda x: -x["count"],
        )[:5]

    except Exception as exc:
        digest["errors"].append({"event_type": "DIGEST_ERROR", "detail": str(exc)})

    return digest


# ══════════════════════════════════════════════════════════════════════════════
# Railway log tail (uptime alerts)
# ══════════════════════════════════════════════════════════════════════════════

def get_railway_log_tail(n: int = 20) -> list[str] | None:
    # TODO: wire Railway log tail once a stable long-lived API token is available
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Uptime watcher — consecutive-failure state machine for /health alerts
# ══════════════════════════════════════════════════════════════════════════════

_UPTIME_FAILURE_THRESHOLD = 2


class UptimeWatcher:
    """
    Tracks consecutive /health failures and fires exactly one alert per
    outage — on the transition into a down state — plus one recovery alert
    when /health returns ok after an active outage. Never fires on a single
    blip; never double-fires while an outage continues (flapping-safe).
    """

    def __init__(
        self,
        check_fn=check_flask_health,
        on_down=None,
        on_recovery=None,
        failure_threshold: int = _UPTIME_FAILURE_THRESHOLD,
    ) -> None:
        self._check_fn = check_fn
        self._on_down = on_down
        self._on_recovery = on_recovery
        self._threshold = failure_threshold
        self.consecutive_failures = 0
        self.in_outage = False

    def poll(self) -> dict:
        """Run one check cycle. Returns the raw check result dict."""
        result = self._check_fn()

        if result.get("status") == "ok":
            if self.in_outage and self._on_recovery:
                self._on_recovery(result)
            self.consecutive_failures = 0
            self.in_outage = False
            return result

        self.consecutive_failures += 1
        if self.consecutive_failures >= self._threshold and not self.in_outage:
            self.in_outage = True
            if self._on_down:
                self._on_down(result, self.consecutive_failures)

        return result
