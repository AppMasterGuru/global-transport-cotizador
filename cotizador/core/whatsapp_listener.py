"""
Inbound WhatsApp listener — mirrors core/email_listener.py exactly.

Accepts Meta WhatsApp Business API webhook payloads, extracts structured
quote request data, and routes into the same quote pipeline as the email
listener. The rest of the pipeline is channel-agnostic.

Entry point:
    process_whatsapp_message(raw_payload: dict) -> dict

Stub mode:
    When WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID are absent from
    .env, the module logs a warning and runs in STUB mode — payloads can be
    parsed and routed but replies cannot be sent.

Reference: Meta WhatsApp Business API — Webhooks
    https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from core.db import audit
from core.email_listener import (
    REQUIRED_FIELDS,
    _detect_language_keyword,
    _empty_result,
    _stub_parse,
    _live_parse,
    _STUB_MODE as _EMAIL_STUB_MODE,
    _queue_acknowledgment,
)

logger = logging.getLogger(__name__)

# ── WhatsApp credential check ─────────────────────────────────────────────────

_WA_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
_WA_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
STUB_MODE: bool = not (_WA_ACCESS_TOKEN and _WA_PHONE_NUMBER_ID)

if STUB_MODE:
    logger.warning(
        "WhatsApp listener running in STUB MODE — "
        "WHATSAPP_ACCESS_TOKEN and/or WHATSAPP_PHONE_NUMBER_ID not set. "
        "Payloads will be parsed and routed but replies cannot be sent."
    )

# Whether to use Claude API for parsing (mirrors email_listener logic)
_PARSE_WITH_CLAUDE = not _EMAIL_STUB_MODE


# ── Payload extraction ────────────────────────────────────────────────────────

def extract_message(raw_payload: dict) -> dict | None:
    """
    Extract the first inbound text message from a Meta webhook payload.

    Meta webhook structure (simplified):
        {
          "object": "whatsapp_business_account",
          "entry": [{
            "changes": [{
              "value": {
                "messages": [{
                  "from": "<phone>",
                  "id": "<wamid>",
                  "timestamp": "<unix_ts>",
                  "type": "text",
                  "text": {"body": "<message text>"}
                }],
                "contacts": [{"profile": {"name": "<display name>"}}]
              }
            }]
          }]
        }

    Returns a normalised dict:
        {
          "message_id": str,
          "from_number": str,
          "display_name": str | None,
          "body": str,
          "timestamp": str (ISO 8601),
          "has_attachments": bool,
          "attachment_ids": list[str],
        }

    Returns None if the payload contains no processable message.
    """
    try:
        entry = raw_payload.get("entry", [{}])[0]
        change = entry.get("changes", [{}])[0]
        value = change.get("value", {})

        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        msg_type = msg.get("type", "")

        # Extract text body
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")
        elif msg_type in ("image", "document", "audio", "video"):
            # Non-text message — extract caption if present, else use type as body
            media = msg.get(msg_type, {})
            body = media.get("caption", f"[{msg_type} attachment]")
        else:
            body = ""

        # Contact display name (optional — not always present)
        contacts = value.get("contacts", [])
        display_name = (
            contacts[0].get("profile", {}).get("name") if contacts else None
        )

        # Attachment IDs for non-text media
        attachment_ids: list[str] = []
        if msg_type in ("image", "document", "audio", "video"):
            media_id = msg.get(msg_type, {}).get("id")
            if media_id:
                attachment_ids.append(media_id)

        # Timestamp: Meta sends Unix epoch as a string
        raw_ts = msg.get("timestamp", "")
        try:
            ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc).isoformat()
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc).isoformat()

        return {
            "message_id":       msg.get("id", ""),
            "from_number":      msg.get("from", ""),
            "display_name":     display_name,
            "body":             body,
            "timestamp":        ts,
            "has_attachments":  bool(attachment_ids),
            "attachment_ids":   attachment_ids,
        }

    except (IndexError, KeyError, TypeError):
        return None


# ── Parse (reuses email_listener logic) ──────────────────────────────────────

def parse_whatsapp_request(message: dict) -> dict:
    """
    Parse a normalised WhatsApp message dict into a structured quote request.

    Uses Claude API when ANTHROPIC_API_KEY is set (same path as email_listener).
    Falls back to keyword-based stub parse otherwise.

    Logs QUOTE_REQUEST_RECEIVED to audit trail.
    """
    body = message.get("body", "")

    if _PARSE_WITH_CLAUDE:
        result = _live_parse(body)
    else:
        result = _stub_parse(body)

    # Override customer_name from WhatsApp display name if not extracted
    if not result.get("customer_name") and message.get("display_name"):
        result["customer_name"] = message["display_name"]

    # WhatsApp sender phone replaces customer_email as the contact identifier
    if not result.get("customer_email"):
        result["customer_email"] = message.get("from_number", "")

    audit(
        "QUOTE_REQUEST_RECEIVED",
        None,
        "whatsapp_listener",
        {
            "detected_language": result.get("detected_language"),
            "service_type":      result.get("service_type"),
            "direction":         result.get("direction"),
            "from_number":       message.get("from_number"),
            "stub_mode":         not _PARSE_WITH_CLAUDE,
        },
    )
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def process_whatsapp_message(raw_payload: dict) -> dict:
    """
    Accept a Meta WhatsApp Business API webhook payload and return a structured
    quote request object — same shape as process_inbound_emails() output.

    The returned dict is channel-agnostic: the rest of the pipeline treats it
    identically to an email-sourced request. The only addition is:
        inbound_channel: "whatsapp"

    Also generates and queues a multilingual auto-acknowledgment (mirrors
    email_listener behaviour).

    Args:
        raw_payload: Full Meta webhook POST body (parsed JSON).

    Returns:
        Structured quote request dict with all REQUIRED_FIELDS plus:
            inbound_channel, _wa_message_id, _wa_from, _wa_display_name,
            _wa_timestamp, _wa_has_attachments, _ack
        Returns a minimal error dict if the payload contains no message.
    """
    from core.acknowledgment import detect_and_acknowledge  # noqa: PLC0415

    message = extract_message(raw_payload)

    if message is None:
        logger.warning("WhatsApp webhook payload contained no processable message.")
        return {
            "inbound_channel": "whatsapp",
            "error": "no_message",
            "raw_payload": raw_payload,
        }

    parsed = parse_whatsapp_request(message)

    # Attach WhatsApp envelope metadata (mirrors email _email_* fields)
    parsed["inbound_channel"]    = "whatsapp"
    parsed["_wa_message_id"]     = message.get("message_id")
    parsed["_wa_from"]           = message.get("from_number")
    parsed["_wa_display_name"]   = message.get("display_name")
    parsed["_wa_timestamp"]      = message.get("timestamp")
    parsed["_wa_has_attachments"] = message.get("has_attachments", False)

    # Auto-acknowledgment (same logic as email_listener)
    ack: dict = {}
    body = message.get("body", "")
    if body:
        try:
            ack = detect_and_acknowledge(body)
            _queue_acknowledgment(
                ack,
                {
                    "from":     message.get("from_number", ""),
                    "subject":  f"WhatsApp from {message.get('display_name') or message.get('from_number', '')}",
                    "id":       message.get("message_id", ""),
                },
            )
            audit(
                "ACK_QUEUED",
                None,
                "whatsapp_listener",
                {
                    "message_id":     message.get("message_id"),
                    "language":       ack.get("language"),
                    "detected_topic": ack.get("detected_topic"),
                    "response_hours": ack.get("response_hours"),
                    "stub_mode":      STUB_MODE,
                },
            )
        except Exception:
            pass  # Ack failure never blocks quote processing

    parsed["_ack"] = ack
    return parsed
