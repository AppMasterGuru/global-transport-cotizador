"""
Provider status computation for the quote detail panel.

Status per expected provider:
  GREEN  — reply received (parse_status = 'parsed')
  ORANGE — contacted, no reply, < 24 h since first contact
  RED    — contacted, no reply, >= 24 h since first contact
  GREY   — expected for this mode but not yet contacted
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

OVERDUE_HOURS = 24


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _detail(row: dict) -> dict:
    raw = row.get("detail_json") or row.get("detail") or {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw


def compute_provider_statuses(
    expected_providers: list[str],
    audit_log: list[dict],
    replies: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """
    Return one status dict per expected provider.

    Output keys per row:
      provider     str
      status       "green" | "orange" | "red" | "grey"
      contacted_at datetime | None  — earliest PROVIDER_EMAIL_SENT ts
      reply        dict | None      — first matching provider_reply row
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # contacted map: provider name → earliest send timestamp
    contacted: dict[str, datetime] = {}
    for entry in audit_log:
        if entry.get("event_type") != "PROVIDER_EMAIL_SENT":
            continue
        detail = _detail(entry)
        name = detail.get("provider", "")
        ts = _parse_ts(entry.get("ts"))
        if name and ts:
            if name not in contacted or ts < contacted[name]:
                contacted[name] = ts

    # replies map: provider_name → first reply row
    replied: dict[str, dict] = {}
    for r in replies:
        name = r.get("provider_name", "")
        if name and name not in replied:
            replied[name] = r

    rows = []
    for provider in expected_providers:
        contacted_at = contacted.get(provider)
        reply = replied.get(provider)

        if reply is not None:
            status = "green"
        elif contacted_at is not None:
            age = now - contacted_at
            status = "orange" if age < timedelta(hours=OVERDUE_HOURS) else "red"
        else:
            status = "grey"

        rows.append({
            "provider":     provider,
            "status":       status,
            "contacted_at": contacted_at,
            "reply":        reply,
        })

    return rows


def build_chase_email(provider: str, quote: dict) -> dict:
    """Pre-filled chase email for a RED (overdue) provider."""
    ref = quote.get("reference_code", "")
    origin = quote.get("origin", "Lima")
    destination = quote.get("destination", "")
    subject = (
        f"RE: {ref} — Solicitud de tarifa {origin} → {destination} — Recordatorio"
    )
    body = (
        f"Estimados señores de {provider},\n\n"
        f"Me permito hacer seguimiento a nuestra solicitud de tarifa, "
        f"código de referencia {ref}.\n"
        f"Agradecería su cotización a la brevedad.\n\n"
        f"Muchas gracias."
    )
    return {"provider": provider, "subject": subject, "body": body}
