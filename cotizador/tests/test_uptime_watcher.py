"""
Tests for the dedicated uptime watcher:
  core/monitor.py       — UptimeWatcher state machine, get_railway_log_tail
  core/slack_alerter.py — send_uptime_down_alert
  uptime_daemon.py       — build_watcher() wiring

All tests are network-free: UptimeWatcher takes injected check/alert
callables, and Slack stub mode (no SLACK_WEBHOOK_URL) is forced.
"""

from __future__ import annotations

import os

import pytest

os.environ.pop("SLACK_WEBHOOK_URL", None)

from core.monitor import UptimeWatcher, get_railway_log_tail  # noqa: E402
from core.slack_alerter import send_uptime_down_alert  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# UptimeWatcher — consecutive-failure state machine
# ═══════════════════════════════════════════════════════════════════════════════

def _make_watcher(statuses):
    """Build a watcher whose check_fn pops from `statuses` (a list of dicts)."""
    it = iter(statuses)
    alerts = []
    recoveries = []
    watcher = UptimeWatcher(
        check_fn=lambda: next(it),
        on_down=lambda result, count: alerts.append((result, count)),
        on_recovery=lambda result: recoveries.append(result),
    )
    return watcher, alerts, recoveries


def test_single_failure_does_not_alert():
    watcher, alerts, recoveries = _make_watcher([{"status": "down", "error": "boom"}])
    watcher.poll()
    assert alerts == []
    assert watcher.consecutive_failures == 1
    assert watcher.in_outage is False


def test_two_consecutive_failures_fire_exactly_one_alert():
    watcher, alerts, recoveries = _make_watcher([
        {"status": "down", "error": "boom"},
        {"status": "down", "error": "boom"},
    ])
    watcher.poll()
    watcher.poll()
    assert len(alerts) == 1
    assert alerts[0][1] == 2  # consecutive_failures passed to on_down
    assert watcher.in_outage is True


def test_continued_failures_do_not_double_fire():
    statuses = [{"status": "down", "error": "boom"}] * 5
    watcher, alerts, recoveries = _make_watcher(statuses)
    for _ in range(5):
        watcher.poll()
    assert len(alerts) == 1  # still one alert for the same ongoing outage


def test_recovery_after_outage_fires_exactly_one_recovery_alert():
    watcher, alerts, recoveries = _make_watcher([
        {"status": "down", "error": "boom"},
        {"status": "down", "error": "boom"},
        {"status": "ok"},
    ])
    watcher.poll()
    watcher.poll()
    watcher.poll()
    assert len(alerts) == 1
    assert len(recoveries) == 1
    assert watcher.in_outage is False
    assert watcher.consecutive_failures == 0


def test_single_blip_then_ok_never_alerts_or_recovers():
    watcher, alerts, recoveries = _make_watcher([
        {"status": "down", "error": "boom"},
        {"status": "ok"},
    ])
    watcher.poll()
    watcher.poll()
    assert alerts == []
    assert recoveries == []  # never entered outage, so no recovery alert either


def test_flapping_fires_one_alert_and_one_recovery_per_outage():
    statuses = [
        {"status": "down", "error": "boom"},
        {"status": "down", "error": "boom"},   # outage #1 alert
        {"status": "ok"},                       # outage #1 recovery
        {"status": "down", "error": "boom"},
        {"status": "down", "error": "boom"},   # outage #2 alert
        {"status": "ok"},                       # outage #2 recovery
    ]
    watcher, alerts, recoveries = _make_watcher(statuses)
    for _ in range(6):
        watcher.poll()
    assert len(alerts) == 2
    assert len(recoveries) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Railway log tail — graceful skip without credentials
# ═══════════════════════════════════════════════════════════════════════════════

def test_railway_log_tail_none_without_credentials(monkeypatch):
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    assert get_railway_log_tail() is None


def test_railway_log_tail_none_on_api_failure(monkeypatch):
    monkeypatch.setenv("RAILWAY_API_TOKEN", "fake-token")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "fake-project")
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "fake-service")

    def _raise(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr("core.monitor._requests.post", _raise)
    assert get_railway_log_tail() is None


# ═══════════════════════════════════════════════════════════════════════════════
# Slack dispatch — send_uptime_down_alert
# ═══════════════════════════════════════════════════════════════════════════════

def test_send_uptime_down_alert_stub_without_logs(capsys):
    result = send_uptime_down_alert(
        consecutive_failures=2,
        last_error="HTTP 500",
        timestamp_utc="2026-06-18T12:00:00+00:00",
        log_lines=None,
    )
    assert result is True
    captured = capsys.readouterr()
    assert "DOWN" in captured.out
    assert "HTTP 500" in captured.out


def test_send_uptime_down_alert_includes_log_lines(capsys):
    send_uptime_down_alert(
        consecutive_failures=2,
        last_error="HTTP 500",
        timestamp_utc="2026-06-18T12:00:00+00:00",
        log_lines=["log line one", "log line two"],
    )
    captured = capsys.readouterr()
    assert "log line one" in captured.out
    assert "log line two" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# uptime_daemon.py — wiring (no loop execution)
# ═══════════════════════════════════════════════════════════════════════════════

def test_build_watcher_wires_check_and_alert_fns():
    import sys
    _scripts = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    )
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import uptime_daemon

    watcher = uptime_daemon.build_watcher()
    assert isinstance(watcher, UptimeWatcher)
    assert watcher._check_fn is not None
    assert watcher._on_down is not None
    assert watcher._on_recovery is not None


# ═══════════════════════════════════════════════════════════════════════════════
# uptime_daemon.py — background HTTP healthcheck server (required by Railway)
# ═══════════════════════════════════════════════════════════════════════════════

def test_health_server_responds_200_ok():
    import sys

    import requests

    _scripts = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
    )
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    import uptime_daemon

    server = uptime_daemon.start_health_server(0)  # port 0 → OS-assigned free port
    try:
        port = server.server_port
        resp = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    finally:
        server.shutdown()
