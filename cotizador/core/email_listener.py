"""
Inbound email listener — Pipeline #3 kicker.

fetch_pending_emails() → Microsoft Graph API (unread messages from LISTENER_MAILBOX).
  Falls back to 3 hardcoded sample emails when Graph credentials are absent
  (GRAPH_CLIENT_ID + GRAPH_CLIENT_SECRET not set), so tests never need real credentials.

parse_quote_request(raw_email_text) → Uses Claude API when ANTHROPIC_API_KEY is set.
  Falls back to keyword-based stub parse when key is absent.

process_inbound_emails() → Fetches + routes emails (provider replies or client requests).
  Logs each event to audit trail.

Graph config (from .env / Railway env vars):
  GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, GRAPH_TENANT_ID  — Azure app credentials
  LISTENER_MAILBOX   — mailbox to poll  (default: pricing@gt.com.pe)
  LISTENER_SINCE     — ISO date lower bound, e.g. 2026-05-21 (avoids replaying history)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import requests as _requests

from core.db import audit

# ── Graph listener config ────────────────────────────────────────────────────

_LISTENER_MAILBOX = os.getenv("LISTENER_MAILBOX", "pricing@gt.com.pe")
_LISTENER_SINCE   = os.getenv("LISTENER_SINCE", "")   # e.g. "2026-05-21"

# Live fetch is active only when Azure app credentials are present.
# Tests run without .env so this is False in the test suite → stubs used.
_LISTENER_CONFIGURED = bool(
    os.getenv("GRAPH_CLIENT_ID") and os.getenv("GRAPH_CLIENT_SECRET")
)

_GRAPH_INBOX = (
    f"https://graph.microsoft.com/v1.0"
    f"/users/{_LISTENER_MAILBOX}/mailFolders/Inbox/messages"
)

# ── Stub mode — no API key needed for demo / testing ─────────────────────────

_STUB_MODE = not os.getenv("ANTHROPIC_API_KEY")

# ── Required output fields ────────────────────────────────────────────────────

REQUIRED_FIELDS: list[str] = [
    "customer_name",
    "customer_email",
    "origin_city",
    "origin_country",
    "destination_city",
    "destination_country",
    "commodity",
    "weight_kg",
    "weight_unit",
    "volume_cbm",
    "packages",
    "incoterm",
    "service_type",
    "direction",
    "urgency",
    "detected_language",
    "raw_text",
]

# ── Hardcoded sample emails (STUB) ────────────────────────────────────────────
# Replace fetch_pending_emails() body with real IMAP/Graph API fetch when
# SMTP credentials arrive from Vania.

_SAMPLE_EMAILS: list[dict] = [
    {
        "id": "stub-001",
        "from": "carlos.mendoza@peruexports.com",
        "subject": "Solicitud de cotización — carga LCL Lima a Hamburgo",
        "received_at": "2026-05-14T08:30:00Z",
        "body": (
            "Buenos días,\n\n"
            "Mi nombre es Carlos Mendoza, de Perú Exports SAC. Necesitamos cotización "
            "para envío de carga LCL desde Lima (Callao) hasta el puerto de Hamburgo, Alemania.\n\n"
            "Detalles de la carga:\n"
            "- Mercancía: Quinua orgánica en sacos de 25 kg\n"
            "- Peso total: 2,500 kg\n"
            "- Volumen: 8 CBM aproximadamente\n"
            "- Cantidad: 100 sacos\n"
            "- Incoterm: FOB Callao\n\n"
            "Necesitamos el embarque para la primera quincena de junio. "
            "Por favor incluir todos los cargos en origen.\n\n"
            "Muchas gracias,\n"
            "Carlos Mendoza\n"
            "carlos.mendoza@peruexports.com\n"
            "Perú Exports SAC"
        ),
    },
    {
        "id": "stub-002",
        "from": "sarah.johnson@miamicargo.com",
        "subject": "FCL Import Quote Request — Miami to Callao",
        "received_at": "2026-05-14T10:15:00Z",
        "body": (
            "Hello,\n\n"
            "I'm Sarah Johnson from Miami Cargo Solutions. We need a quote for an FCL "
            "shipment from Miami, USA to Callao, Peru.\n\n"
            "Shipment details:\n"
            "- Commodity: Industrial machinery (non-hazardous)\n"
            "- Container: 1 x 40' HC\n"
            "- Weight: approximately 18,000 kg\n"
            "- Volume: 62 CBM\n"
            "- Incoterm: DAP Lima warehouse\n\n"
            "This is urgent — we need the cargo to arrive before June 30th. "
            "Please quote door-to-door including customs clearance in Lima.\n\n"
            "Best regards,\n"
            "Sarah Johnson\n"
            "sarah.johnson@miamicargo.com\n"
            "Miami Cargo Solutions LLC"
        ),
    },
    {
        "id": "stub-003",
        "from": "hans.mueller@berlintrade.de",
        "subject": "Luftfracht Anfrage — Frankfurt nach Lima",
        "received_at": "2026-05-14T02:45:00Z",
        "body": (
            "Sehr geehrte Damen und Herren,\n\n"
            "mein Name ist Hans Müller von Berlin Trade GmbH. Wir benötigen eine "
            "Offerte für einen Luftfrachttransport von Frankfurt (FRA) nach Lima (LIM), Peru.\n\n"
            "Sendungsdetails:\n"
            "- Ware: Medizinische Geräte (keine Gefahrgüter)\n"
            "- Gewicht: 320 kg\n"
            "- Volumen: 1,8 CBM\n"
            "- Abmessungen: 3 Pakete à 120 × 80 × 60 cm\n"
            "- Incoterm: DAP Lima\n\n"
            "Die Sendung ist dringend — Lieferung bis spätestens 25. Mai 2026 erforderlich. "
            "Bitte um Angebot inklusive Zollabwicklung in Peru.\n\n"
            "Mit freundlichen Grüßen,\n"
            "Hans Müller\n"
            "hans.mueller@berlintrade.de\n"
            "Berlin Trade GmbH"
        ),
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_result(raw_text: str, language: str = "es") -> dict:
    """Return a zeroed-out result dict (all fields None) for use on parse failure."""
    result = {f: None for f in REQUIRED_FIELDS}
    result["detected_language"] = language
    result["raw_text"] = raw_text
    return result


def _detect_language_keyword(text: str) -> str:
    """Quick keyword-based language detection. Returns ISO 639-1 code."""
    t = text.lower()
    if any(w in t for w in ["sehr geehrte", "ich benötige", "anfrage", "luftfracht",
                             "mit freundlichen", "offerte", "sendung"]):
        return "de"
    if any(w in t for w in ["estimado", "cotización", "necesitamos", "mercancía",
                             "muchas gracias", "buenos días", "favor"]):
        return "es"
    if any(w in t for w in ["dear ", "please quote", "best regards", "we need",
                             "shipment", "commodity"]):
        return "en"
    return "es"  # Default to Spanish (GT's primary market)


def _stub_parse(raw_text: str) -> dict:
    """
    Keyword-based parse — no Claude API required.
    Returns a best-effort extraction from the email text.
    Used when ANTHROPIC_API_KEY is not set (demo/test mode).
    """
    text = raw_text
    text_lower = text.lower()

    lang = _detect_language_keyword(text)

    # Service type
    if any(w in text_lower for w in ["aereo", "aéreo", "air freight", "luftfracht",
                                     "air cargo", "airfreight", "avión"]):
        service_type = "aéreo"
    elif "fcl" in text_lower or "full container" in text_lower or "40'" in text_lower or "20'" in text_lower:
        service_type = "FCL"
    elif "lcl" in text_lower or "less than container" in text_lower or "grupaje" in text_lower:
        service_type = "LCL"
    else:
        service_type = "unknown"

    # Direction (from GT's Peru perspective)
    if any(w in text_lower for w in ["export", "exportación", "from lima",
                                     "desde lima", "desde callao", "callao to"]):
        direction = "export"
    elif any(w in text_lower for w in ["import", "importación", "to lima",
                                       "a lima", "callao", "nach lima", "to callao"]):
        direction = "import"
    else:
        direction = "unknown"

    # Urgency
    if any(w in text_lower for w in ["urgente", "urgent", "dringend", "asap",
                                     "lo antes posible", "inmediato"]):
        urgency = "asap"
    elif any(w in text_lower for w in ["antes del", "before", "bis spätestens",
                                       "no later than", "deadline"]):
        urgency = "specific_date"
    else:
        urgency = "flexible"

    return _empty_result(raw_text, lang) | {
        "service_type": service_type,
        "direction":    direction,
        "urgency":      urgency,
        "detected_language": lang,
    }


# ── Live parse (Claude API) ───────────────────────────────────────────────────

_PARSE_SYSTEM = (
    "You are a freight-forwarding intake specialist at Global Transport SAC, Lima, Peru. "
    "Extract structured data from inbound quote request emails. "
    "Return ONLY a JSON object with exactly these fields:\n"
    "customer_name, customer_email, origin_city, origin_country, "
    "destination_city, destination_country, commodity, "
    "weight_kg (number or null), weight_unit (kg/lbs/tons), "
    "volume_cbm (number or null), packages (integer or null), "
    "incoterm (FOB/CIF/DAP/DDP/EXW/FCA or null), "
    "service_type (aéreo/LCL/FCL/unknown), "
    "direction (export/import/unknown — from Peru's perspective), "
    "urgency (asap/specific_date/flexible/unknown), "
    "detected_language (ISO 639-1: es/en/de/zh/fr/pt/etc).\n"
    "If a field cannot be determined, use null. Never invent information."
)


def _live_parse(raw_email_text: str) -> dict:
    """
    Parse using Claude API (claude-sonnet-4-20250514).
    Returns structured dict. On any failure, returns _empty_result.
    """
    import anthropic  # noqa: PLC0415 — lazy import, only when API key present

    client = anthropic.Anthropic()
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            system=_PARSE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract structured data from this inbound freight inquiry email:\n\n"
                        f"{raw_email_text[:3000]}"
                    ),
                }
            ],
        )
        raw_json = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw_json.startswith("```"):
            raw_json = "\n".join(raw_json.split("\n")[1:-1])
        parsed = json.loads(raw_json)

        # Ensure all required fields are present (fill missing with None)
        result = _empty_result(raw_email_text, parsed.get("detected_language", "es"))
        for field in REQUIRED_FIELDS:
            if field != "raw_text":
                result[field] = parsed.get(field)
        result["detected_language"] = parsed.get("detected_language", "es")
        return result

    except Exception:
        lang = _detect_language_keyword(raw_email_text)
        return _empty_result(raw_email_text, lang)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_quote_request(raw_email_text: str) -> dict:
    """
    Parse a raw inbound email and extract freight quote parameters.

    Uses Claude API (claude-sonnet-4-20250514) when ANTHROPIC_API_KEY is set.
    Falls back to keyword-based stub parse when key is absent.

    Logs QUOTE_REQUEST_RECEIVED to audit trail on every call.

    Args:
        raw_email_text: Full email body text in any language.

    Returns:
        Dict with all REQUIRED_FIELDS populated (None where not extractable).
    """
    if _STUB_MODE:
        result = _stub_parse(raw_email_text)
    else:
        result = _live_parse(raw_email_text)

    audit(
        "QUOTE_REQUEST_RECEIVED",
        None,
        "email_listener",
        {
            "detected_language": result.get("detected_language"),
            "service_type":      result.get("service_type"),
            "direction":         result.get("direction"),
            "customer_email":    result.get("customer_email"),
            "stub_mode":         _STUB_MODE,
        },
    )
    return result


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities. Used when provider reply is HTML-only."""
    import html as _html_mod  # noqa: PLC0415
    text = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", html,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html_mod.unescape(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _mark_as_read(token: str, msg_id: str) -> None:
    """PATCH message to isRead=true. Swallowed on error — never blocks the pipeline."""
    try:
        url = (
            f"https://graph.microsoft.com/v1.0"
            f"/users/{_LISTENER_MAILBOX}/messages/{msg_id}"
        )
        _requests.patch(
            url,
            json={"isRead": True},
            headers={
                "Authorization":  f"Bearer {token}",
                "Content-Type":   "application/json",
            },
            timeout=10,
        )
    except Exception:
        pass


def _graph_fetch_emails() -> list[dict]:
    """
    Fetch unread messages from the Graph API inbox, mark each as read,
    and return them in the standard dict format.
    Falls back to stub list if token acquisition fails.
    """
    from core.drive import get_graph_token  # noqa: PLC0415 — lazy to avoid circular import

    token = get_graph_token()
    if not token:
        audit("LISTENER_POLL", None, "email_listener",
              {"status": "TOKEN_FAILED", "mailbox": _LISTENER_MAILBOX})
        return _SAMPLE_EMAILS

    odata_filter = "isRead eq false"
    if _LISTENER_SINCE:
        odata_filter += f" and receivedDateTime ge {_LISTENER_SINCE}T00:00:00Z"

    try:
        resp = _requests.get(
            _GRAPH_INBOX,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "$filter":  odata_filter,
                "$select":  "id,subject,from,body,receivedDateTime",
                "$top":     "50",
                "$orderby": "receivedDateTime asc",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        audit("LISTENER_POLL", None, "email_listener",
              {"status": "FETCH_ERROR", "error": str(exc), "mailbox": _LISTENER_MAILBOX})
        return _SAMPLE_EMAILS

    results: list[dict] = []
    for msg in resp.json().get("value", []):
        sender_obj  = (msg.get("from") or {}).get("emailAddress") or {}
        body_obj    = msg.get("body") or {}
        body_text   = body_obj.get("content", "")
        if (body_obj.get("contentType") or "").lower() == "html":
            body_text = _strip_html(body_text)

        results.append({
            "id":          msg.get("id", ""),
            "from":        sender_obj.get("address", ""),
            "subject":     msg.get("subject", ""),
            "received_at": msg.get("receivedDateTime", ""),
            "body":        body_text,
        })
        _mark_as_read(token, msg["id"])

    return results


def fetch_pending_emails() -> list[dict]:
    """
    Return pending inbound emails from the pricing@gt.com.pe inbox.

    Live mode  (GRAPH_CLIENT_ID + GRAPH_CLIENT_SECRET set):
      Fetches unread messages via Microsoft Graph API, marks each read so it
      is not processed again on the next poll.

    Stub mode  (credentials absent — tests and local dev without .env):
      Returns the 3 hardcoded sample emails in _SAMPLE_EMAILS.
    """
    if _LISTENER_CONFIGURED:
        return _graph_fetch_emails()
    return _SAMPLE_EMAILS


def _queue_acknowledgment(ack: dict, email_meta: dict) -> None:
    """
    Log a pending acknowledgment to CACHE_DIR/pending_acks.jsonl.

    When SMTP credentials are not yet configured, acknowledgments are queued
    here instead of sent. Once SMTP is live, the queue can be replayed.
    Each line is a self-contained JSON object with: ts, language, subject,
    recipient_email, detected_topic, body.
    """
    import json as _json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    cache_dir = os.getenv("CACHE_DIR", ".")
    queue_path = Path(cache_dir) / "pending_acks.jsonl"

    entry = {
        "ts":              datetime.now(timezone.utc).isoformat(),
        "language":        ack.get("language", "es"),
        "subject":         ack.get("subject", ""),
        "body":            ack.get("body", ""),
        "detected_topic":  ack.get("detected_topic", ""),
        "response_hours":  ack.get("response_hours", 4),
        "recipient_email": email_meta.get("from", ""),
        "email_subject":   email_meta.get("subject", ""),
        "email_id":        email_meta.get("id", ""),
    }

    try:
        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Never crash the listener over a queue write failure


def process_inbound_emails(auto_ack: bool = True) -> list[dict]:
    """
    Fetch all pending inbound emails. Routes each to the correct pipeline:

    - Provider reply (subject contains reference code OR known sender domain):
        → process_provider_reply()  (rate extraction, DB store, audit, costeo update)
        → no acknowledgment sent (provider replies don't need a receipt ack)

    - Client quote request (everything else):
        → parse_quote_request()  (structured extraction, audit)
        → auto-acknowledgment queued when auto_ack=True

    Returns list of result dicts (one per email), each tagged with _email_type:
      'provider_reply'  — provider rate response
      'client_request'  — new client quote inquiry
    """
    from core.acknowledgment import detect_and_acknowledge          # noqa: PLC0415
    from core.provider_reply_parser import (                        # noqa: PLC0415
        is_provider_reply,
        process_provider_reply,
    )

    emails = fetch_pending_emails()
    results: list[dict] = []

    for email in emails:
        if is_provider_reply(email):
            # ── Provider rate reply ───────────────────────────────────────────
            result = process_provider_reply(email)
            results.append(result)
            continue

        # ── Client quote request ──────────────────────────────────────────────
        parsed = parse_quote_request(email["body"])
        parsed["_email_type"]    = "client_request"
        parsed["_email_id"]      = email.get("id")
        parsed["_email_from"]    = email.get("from")
        parsed["_email_subject"] = email.get("subject")
        parsed["_received_at"]   = email.get("received_at")

        ack: dict = {}
        if auto_ack:
            try:
                ack = detect_and_acknowledge(email["body"])
                _queue_acknowledgment(ack, email)
                audit(
                    "ACK_QUEUED",
                    None,
                    "email_listener",
                    {
                        "email_id":       email.get("id"),
                        "language":       ack.get("language"),
                        "detected_topic": ack.get("detected_topic"),
                        "response_hours": ack.get("response_hours"),
                    },
                )
            except Exception:
                pass  # Ack failure never blocks quote processing

        parsed["_ack"] = ack
        results.append(parsed)

    return results
