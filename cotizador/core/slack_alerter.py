"""
GT Cotizador — Slack alerter for Barney's monitoring channel.

STUB MODE (default): when SLACK_WEBHOOK_URL is not set, all alerts are
logged to the console instead of sent to Slack. Set SLACK_WEBHOOK_URL
to activate real Slack delivery.

Usage:
    from core.slack_alerter import send_alert, send_health_alert
    send_alert("critical", "Flask is down", "Health check returned 500")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests as _requests

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_WEBHOOK_URL  = os.getenv("SLACK_WEBHOOK_URL", "")
_CHANNEL      = os.getenv("SLACK_ALERT_CHANNEL", "#gt-monitor")
_ENABLED      = os.getenv("MONITOR_ENABLED", "true").lower() not in ("false", "0", "no")
_STUB_MODE    = not _WEBHOOK_URL
_LIMA_TZ      = ZoneInfo("America/Lima")

# Severity → color (Slack attachment color hex) and emoji
_SEVERITY_CONFIG = {
    "info":     {"color": "#2196F3", "emoji": "ℹ️"},
    "warning":  {"color": "#FF9800", "emoji": "⚠️"},
    "critical": {"color": "#F44336", "emoji": "🔴"},
}


# ── Core sender ───────────────────────────────────────────────────────────────

def _lima_now_str() -> str:
    return datetime.now(_LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S Lima")


def _build_blocks(
    severity: str,
    title: str,
    message: str,
    details: dict | None,
) -> list[dict]:
    """Build Slack Block Kit message blocks."""
    cfg    = _SEVERITY_CONFIG.get(severity, _SEVERITY_CONFIG["info"])
    emoji  = cfg["emoji"]
    ts     = _lima_now_str()

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
    ]

    if details:
        fields = []
        for k, v in list(details.items())[:8]:  # Slack limit: 10 fields per section
            fields.append({
                "type": "mrkdwn",
                "text": f"*{k}*\n{v}",
            })
        if fields:
            blocks.append({"type": "section", "fields": fields})

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"GT Cotizador Monitor  ·  {ts}",
            }
        ],
    })

    return blocks


def send_alert(
    severity: str,
    title: str,
    message: str,
    details: dict | None = None,
) -> bool:
    """
    Send a Slack alert (or log to console in stub mode).

    Args:
        severity: "info" | "warning" | "critical"
        title:    Short headline (plain text)
        message:  Body text (supports Slack mrkdwn)
        details:  Optional key-value pairs shown as fields

    Returns True if delivered (or stubbed), False on send failure.
    """
    if not _ENABLED:
        return True

    cfg   = _SEVERITY_CONFIG.get(severity, _SEVERITY_CONFIG["info"])
    color = cfg["color"]
    emoji = cfg["emoji"]

    if _STUB_MODE:
        # Log to console — swap for real Slack once SLACK_WEBHOOK_URL is set
        ts    = _lima_now_str()
        lines = [
            f"\n{'='*60}",
            f"[SLACK STUB] {emoji}  [{severity.upper()}]  {title}",
            f"  {message}",
        ]
        if details:
            for k, v in details.items():
                lines.append(f"  {k}: {v}")
        lines += [f"  {ts}  ·  GT Cotizador Monitor", "="*60]
        print("\n".join(lines))
        return True

    # Real Slack delivery via incoming webhook
    try:
        payload = {
            "channel": _CHANNEL,
            "attachments": [
                {
                    "color": color,
                    "blocks": _build_blocks(severity, title, message, details),
                }
            ],
        }
        resp = _requests.post(
            _WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200 and resp.text == "ok":
            return True
        logger.warning("Slack delivery failed: HTTP %s — %s", resp.status_code, resp.text)
        return False
    except Exception as exc:
        logger.error("Slack send error: %s", exc)
        return False


# ── Typed senders ─────────────────────────────────────────────────────────────

def send_health_alert(health_report: dict) -> bool:
    """
    Send a health alert only if status is 'degraded' or 'critical'.
    Returns True if sent (or not needed), False on failure.
    """
    overall = health_report.get("overall", "healthy")
    if overall == "healthy":
        return True  # Nothing to alert

    severity = "critical" if overall == "critical" else "warning"
    title    = f"GT Cotizador — {overall.upper()}"

    # Summarise which services are down
    down_svcs = []
    for svc in ("flask", "database", "sharepoint", "smtp"):
        svc_data = health_report.get(svc, {})
        if svc_data.get("status") == "down":
            err = svc_data.get("error", "unknown error")
            down_svcs.append(f"{svc}: {err}")

    message = "\n".join(down_svcs) if down_svcs else f"Overall status is {overall}."
    details = {
        "Flask":       health_report.get("flask", {}).get("status", "?"),
        "Database":    health_report.get("database", {}).get("status", "?"),
        "SharePoint":  health_report.get("sharepoint", {}).get("status", "?"),
        "SMTP":        health_report.get("smtp", {}).get("status", "?"),
        "Checked at":  health_report.get("timestamp_lima", "?"),
    }
    return send_alert(severity, title, message, details)


def send_anomaly_alert(anomaly: dict) -> bool:
    """Send a Slack alert for a detected audit anomaly."""
    atype   = anomaly.get("type", "UNKNOWN")
    count   = anomaly.get("count", 0)
    msg     = anomaly.get("message", "Anomaly detected.")
    sev     = anomaly.get("severity", "warning")

    _SUGGESTED_ACTIONS = {
        "QUOTE_PARSE_FAILED_SPIKE": "Check email_listener logs and inbound email format.",
        "ACK_SEND_FAILED_SPIKE":    "Check SMTP credentials and email_sender.py stub mode.",
        "STUCK_PENDING_QUOTES":     "Review pending quotes in dashboard — may need manual approval.",
        "NO_ACTIVITY":              "Check Flask is running and receiving requests.",
    }
    action = _SUGGESTED_ACTIONS.get(atype, "Review audit log for details.")

    details = {
        "Type":             atype,
        "Count":            str(count),
        "Suggested action": action,
    }
    return send_alert(sev, f"Anomaly: {atype}", msg, details)


def send_daily_digest(digest: dict) -> bool:
    """Send the daily activity digest (always sent at 8:00 AM Lima)."""
    title   = "GT Cotizador — Daily Digest"
    error_count = len(digest.get("errors", []))
    message = (
        f"*Last 24 hours:*\n"
        f"• Quotes generated: {digest.get('quotes_generated', 0)}\n"
        f"• Quotes approved: {digest.get('quotes_approved', 0)}\n"
        f"• Quotes sent: {digest.get('quotes_sent', 0)}\n"
        f"• Acknowledgments sent: {digest.get('acks_sent', 0)}\n"
        f"• Errors: {error_count}"
    )
    details: dict = {
        "Uptime":     f"{digest.get('uptime_pct', 100.0):.1f}%",
        "Generated":  digest.get("generated_at", "?"),
    }
    top_issues = digest.get("top_issues", [])
    if top_issues:
        details["Top issue"] = f"{top_issues[0]['type']} ×{top_issues[0]['count']}"

    return send_alert("info", title, message, details)


def send_recovery_alert(service: str, message: str) -> bool:
    """Send a recovery notification when a previously down service comes back up."""
    title   = f"GT Cotizador — {service} recovered"
    details = {"Service": service, "Status": "back online"}
    return send_alert("info", title, message, details)
