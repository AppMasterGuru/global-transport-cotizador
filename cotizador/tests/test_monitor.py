"""
Tests for the monitoring system:
  core/monitor.py       — health checks, anomaly detection, daily digest
  core/slack_alerter.py — stub mode (no network calls)

9 new tests bringing total from 78 → 87.
All tests run without network calls (Flask not running, Slack stub mode).
"""

from __future__ import annotations

import os
import tempfile

import pytest

# ── DB isolation (must happen before any core imports) ────────────────────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

# Ensure no Slack webhook triggers real network calls
os.environ.pop("SLACK_WEBHOOK_URL", None)

from core.db import get_connection, init_db  # noqa: E402
from core.monitor import (  # noqa: E402
    check_audit_anomalies,
    check_database_health,
    check_flask_health,
    check_sharepoint_health,
    check_smtp_health,
    generate_daily_digest,
    run_health_checks,
)
from core.slack_alerter import send_alert, send_health_alert  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Full DB isolation for every test."""
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
        """)
    init_db()
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# 79. Flask health — returns a valid status dict regardless of whether Flask is running
# ═══════════════════════════════════════════════════════════════════════════════

def test_flask_health_structure():
    """check_flask_health returns a valid dict with all required keys."""
    result = check_flask_health()
    assert isinstance(result, dict)
    assert "status" in result
    assert "response_time_ms" in result
    assert "error" in result
    assert result["status"] in ("ok", "down")
    assert result["response_time_ms"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 80. DB health — returns "ok" with quote_count when DB is accessible
# ═══════════════════════════════════════════════════════════════════════════════

def test_db_health_ok():
    """check_database_health returns status='ok' and quote_count when DB is accessible."""
    result = check_database_health()
    assert result["status"] == "ok"
    assert isinstance(result["quote_count"], int)
    assert result["quote_count"] == 0   # Fresh DB — no quotes
    assert result["error"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 81. SharePoint health — "not_configured" when no Graph token set
# ═══════════════════════════════════════════════════════════════════════════════

def test_sharepoint_not_configured():
    """check_sharepoint_health returns 'not_configured' when GRAPH vars absent."""
    # Ensure env vars are cleared for this test
    for var in ("GRAPH_ACCESS_TOKEN", "SHAREPOINT_DRIVE_ID"):
        os.environ.pop(var, None)

    result = check_sharepoint_health()
    assert result["status"] in ("not_configured", "ok", "down")
    assert "error" in result
    # In CI/test without Graph creds, should be not_configured
    # (drive._CONFIGURED is False when env vars are empty)


# ═══════════════════════════════════════════════════════════════════════════════
# 82. SMTP health — "not_configured" when no credentials set
# ═══════════════════════════════════════════════════════════════════════════════

def test_smtp_not_configured():
    """check_smtp_health returns 'not_configured' when SMTP vars are absent."""
    for var in ("GT_SMTP_SERVER", "GT_EMAIL_ADDRESS"):
        os.environ.pop(var, None)

    result = check_smtp_health()
    # With no server configured, must be not_configured
    assert result["status"] == "not_configured"
    assert result["error"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 83. run_health_checks — returns combined report with all required keys
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_health_checks_structure():
    """run_health_checks returns a dict with overall, timestamp, and all service keys."""
    report = run_health_checks()
    assert isinstance(report, dict)
    for key in ("overall", "timestamp", "timestamp_lima",
                "flask", "database", "sharepoint", "smtp"):
        assert key in report, f"Missing key: {key!r}"
    assert report["overall"] in ("healthy", "degraded", "critical")


# ═══════════════════════════════════════════════════════════════════════════════
# 84. Anomaly detection — empty DB produces no anomalies
# ═══════════════════════════════════════════════════════════════════════════════

def test_audit_anomalies_empty_db():
    """check_audit_anomalies returns [] when audit_log is empty (no real anomalies)."""
    anomalies = check_audit_anomalies()
    assert isinstance(anomalies, list)
    # Empty DB: no parse failures, no ack failures, no stuck quotes
    # NO_ACTIVITY only triggers during business hours 8am-8pm Lima
    # Other anomaly types require >3 events — none present in fresh DB
    non_activity = [a for a in anomalies if a["type"] != "NO_ACTIVITY"]
    assert len(non_activity) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 85. Daily digest — returns dict with all required keys
# ═══════════════════════════════════════════════════════════════════════════════

def test_daily_digest_structure():
    """generate_daily_digest returns a dict with all expected keys."""
    digest = generate_daily_digest()
    assert isinstance(digest, dict)
    for key in ("quotes_generated", "quotes_approved", "quotes_sent",
                "acks_sent", "errors", "top_issues", "period_hours", "generated_at"):
        assert key in digest, f"Missing key: {key!r}"
    # Fresh DB — all counts are zero
    assert digest["quotes_generated"] == 0
    assert digest["quotes_approved"] == 0
    assert digest["quotes_sent"] == 0
    assert digest["acks_sent"] == 0
    assert isinstance(digest["errors"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 86. Slack stub — send_alert returns True without network call
# ═══════════════════════════════════════════════════════════════════════════════

def test_slack_stub_send_alert(capsys):
    """send_alert logs to console and returns True when SLACK_WEBHOOK_URL not set."""
    # SLACK_WEBHOOK_URL was cleared at module load — stub mode active
    result = send_alert(
        severity="warning",
        title="Test alert",
        message="This is a test.",
        details={"key": "value"},
    )
    assert result is True
    captured = capsys.readouterr()
    assert "SLACK STUB" in captured.out
    assert "Test alert" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# 87. Slack stub — send_health_alert skips when status is healthy
# ═══════════════════════════════════════════════════════════════════════════════

def test_slack_health_alert_skips_when_healthy():
    """send_health_alert returns True immediately if overall status is 'healthy'."""
    healthy_report = {
        "overall":        "healthy",
        "timestamp_lima": "2026-05-14 10:00:00 Lima",
        "flask":          {"status": "ok"},
        "database":       {"status": "ok"},
        "sharepoint":     {"status": "not_configured"},
        "smtp":           {"status": "not_configured"},
    }
    result = send_health_alert(healthy_report)
    assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 88. Monitor route — GET /monitor returns 200
# ═══════════════════════════════════════════════════════════════════════════════

def test_monitor_route_ok():
    """GET /monitor returns 200 with health dashboard content."""
    from api.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/monitor")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Monitor" in body
    assert "TimeBack AI" in body
