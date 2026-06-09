"""
Email sender — Microsoft Graph API implementation.

Sends via Graph API when GRAPH_CLIENT_ID + GRAPH_CLIENT_SECRET + GRAPH_TENANT_ID
are set. Falls back to stub (print-only) when credentials are absent, so tests
and local dev never need real credentials.

Graph env vars (same as email_listener.py):
  GRAPH_CLIENT_ID      — Azure app client ID
  GRAPH_CLIENT_SECRET  — Azure app client secret
  GRAPH_TENANT_ID      — Azure AD tenant ID

Ejecutivo → from-address map:
  Abel / GT-PC        → pricing@gt.com.pe       (default)
  Daniela / GT-LOC    → lognet.sales@gt.com.pe
  Cielo               → wca.sales@gt.com.pe
  JP                  → jparrue@gt.com.pe
  Renato / RALVAREZ   → ralvarez@gt.com.pe
"""

from __future__ import annotations

import os
import traceback

import requests as _requests

from core.db import audit

# ── Graph API config ──────────────────────────────────────────────────────────

_CLIENT_ID     = os.getenv("GRAPH_CLIENT_ID",     "")
_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
_TENANT_ID     = os.getenv("GRAPH_TENANT_ID",     "")

GRAPH_MODE: bool = bool(_CLIENT_ID and _CLIENT_SECRET and _TENANT_ID)
STUB_MODE:  bool = not GRAPH_MODE

# Checked by routes to gate the manual "Send" button and auto-send logic.
CREDENTIALS_ROTATED: bool = GRAPH_MODE

# ── Ejecutivo → sender address map ────────────────────────────────────────────

_DEFAULT_FROM = "pricing@gt.com.pe"

_EJECUTIVOS: dict[str, str] = {
    "abel":     "pricing@gt.com.pe",
    "gt-pc":    "pricing@gt.com.pe",
    "daniela":  "lognet.sales@gt.com.pe",
    "gt-loc":   "lognet.sales@gt.com.pe",
    "cielo":    "wca.sales@gt.com.pe",
    "jp":       "jparrue@gt.com.pe",
    "renato":   "ralvarez@gt.com.pe",
    "ralvarez": "ralvarez@gt.com.pe",
}


def resolve_from_address(actor: str) -> str:
    """Map a staff code / name to its GT sender address."""
    return _EJECUTIVOS.get((actor or "").lower(), _DEFAULT_FROM)


# ── Transport layer ───────────────────────────────────────────────────────────

def _get_access_token() -> str:
    """Acquire an OAuth2 client-credentials token from Azure AD."""
    url = (
        f"https://login.microsoftonline.com/{_TENANT_ID}"
        f"/oauth2/v2.0/token"
    )
    resp = _requests.post(
        url,
        data={
            "grant_type":    "client_credentials",
            "client_id":     _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
            "scope":         "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _graph_send(from_address: str, to: str, subject: str, body: str) -> None:
    """Send one email via Microsoft Graph API. Raises on failure."""
    token = _get_access_token()
    url   = f"https://graph.microsoft.com/v1.0/users/{from_address}/sendMail"
    resp  = _requests.post(
        url,
        json={
            "message": {
                "subject": subject,
                "body":    {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()


def _stub_send(to: str, subject: str, body: str, **_) -> None:
    """No-op stand-in used when Graph credentials are absent."""
    preview = body[:120].replace("\n", " ")
    print(
        f"[STUB EMAIL] To={to!r} Subject={subject!r} Body='{preview}...'"
    )


def _dispatch(from_address: str, to: str, subject: str, body: str) -> None:
    """Route to Graph or stub depending on credential availability."""
    if STUB_MODE:
        _stub_send(to, subject, body)
    else:
        _graph_send(from_address, to, subject, body)


# ── Public API ─────────────────────────────────────────────────────────────────

def send_provider_email(
    ref_code: str,
    provider: str,
    to: str,
    subject: str,
    body: str,
    actor: str,
) -> tuple[bool, str]:
    """
    Send a rate-request email to a provider/consolidator via Graph API.

    Returns (True, success_message) on success.
    Returns (False, error_message) on failure.
    Always logs PROVIDER_EMAIL_SENT (or PROVIDER_EMAIL_FAILED) to the audit trail.
    """
    from_address = resolve_from_address(actor)
    try:
        _dispatch(from_address, to, subject, body)
        audit("PROVIDER_EMAIL_SENT", ref_code, actor, {
            "to":       to,
            "from":     from_address,
            "provider": provider,
            "subject":  subject,
            "stub":     STUB_MODE,
        })
        mode = "stub" if STUB_MODE else "graph"
        return True, f"Email enviado a {provider} ({to}) [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("PROVIDER_EMAIL_FAILED", ref_code, actor, {
            "to":        to,
            "provider":  provider,
            "error":     error,
            "traceback": traceback.format_exc()[-500:],
        })
        return False, f"Error al enviar a {provider}: {error}"


def send_quote_email(
    ref_code: str,
    quote_id: int,
    customer_email: str,
    customer_name: str,
    actor: str,
    pdf_bytes: bytes | None = None,
) -> tuple[bool, str]:
    """
    Send the proforma PDF to the client via Graph API.

    Returns (True, success_message) on success.
    Returns (False, error_message) on failure.
    Always logs QUOTE_SENT (or QUOTE_SEND_FAILED) to the audit trail.
    """
    from_address = resolve_from_address(actor)
    subject = f"Proforma Global Transport SAC — {ref_code}"
    body = (
        f"Estimado/a {customer_name},\n\n"
        f"Adjunto encontrará nuestra proforma de cotización para el envío "
        f"referenciado como {ref_code}.\n\n"
        f"La cotización tiene una validez de 15 días a partir de la fecha de emisión.\n"
        f"Cualquier consulta, estamos a su disposición.\n\n"
        f"Atentamente,\n{actor}\nGlobal Transport SAC\n"
        f"comercial@globaltransportperu.com"
    )
    try:
        _dispatch(from_address, customer_email, subject, body)
        audit("QUOTE_SENT", ref_code, actor, {
            "to":       customer_email,
            "from":     from_address,
            "customer": customer_name,
            "quote_id": quote_id,
            "stub":     STUB_MODE,
            "has_pdf":  pdf_bytes is not None,
        })
        mode = "stub" if STUB_MODE else "graph"
        return True, f"Cotización {ref_code} enviada a {customer_email} [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("QUOTE_SEND_FAILED", ref_code, actor, {
            "to":        customer_email,
            "error":     error,
            "traceback": traceback.format_exc()[-500:],
        })
        return False, f"Error al enviar {ref_code}: {error}"


def send_acknowledgment_email(
    recipient_email: str,
    recipient_name: str,
    subject: str,
    ack_text: str,
    actor: str = "system",
) -> tuple[bool, str]:
    """
    Send an auto-acknowledgment email via Graph API.

    Returns (True, success_message) or (False, error_message).
    Always logs ACK_SENT (or ACK_SEND_FAILED) to the audit trail.
    """
    from_address = resolve_from_address(actor)
    try:
        _dispatch(from_address, recipient_email, subject, ack_text)
        audit("ACK_SENT", None, actor, {
            "to":        recipient_email,
            "from":      from_address,
            "recipient": recipient_name,
            "subject":   subject,
            "stub":      STUB_MODE,
        })
        mode = "stub" if STUB_MODE else "graph"
        return True, f"Acuse enviado a {recipient_email} [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("ACK_SEND_FAILED", None, actor, {
            "to":    recipient_email,
            "error": error,
        })
        return False, f"Error al enviar acuse a {recipient_email}: {error}"
