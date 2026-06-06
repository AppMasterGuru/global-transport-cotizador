"""
Email sender — stub implementation.

STUB — swap _smtp_send() for real SMTP when Vania delivers credentials.
Config comes from .env: GT_SMTP_SERVER, GT_SMTP_PORT, GT_EMAIL_ADDRESS, GT_EMAIL_PASSWORD

Both public functions log to the immutable audit_log via audit() from core.db
so every send attempt (real or stub) is traceable for BASC compliance.

When credentials arrive:
  1. Set GT_SMTP_SERVER, GT_SMTP_PORT, GT_EMAIL_ADDRESS, GT_EMAIL_PASSWORD in .env
  2. Uncomment _smtp_send() below and delete the stub body
  3. Each ejecutivo sends from their own account — GT_EMAIL_ADDRESS will be
     per-staff (Jean Paul / Abel / Daniela / Cielo). Rotate via the actor param.
"""

from __future__ import annotations

import os
import smtplib
import traceback
from email.message import EmailMessage

from core.db import audit

# ── SMTP config (from .env — not hardcoded) ───────────────────────────────────
_SMTP_SERVER  = os.getenv("GT_SMTP_SERVER",  "smtp.office365.com")
_SMTP_PORT    = int(os.getenv("GT_SMTP_PORT", "587"))
_FROM_ADDRESS = os.getenv("GT_EMAIL_ADDRESS", "")
_FROM_PASSWORD = os.getenv("GT_EMAIL_PASSWORD", "")

_STUB_MODE = not (_FROM_ADDRESS and _FROM_PASSWORD)

# True once SMTP credentials have been rotated to real values — checked by routes
CREDENTIALS_ROTATED: bool = not _STUB_MODE


# ── Real SMTP send (uncomment when Vania delivers credentials) ─────────────────
#
# def _smtp_send(to: str, subject: str, body: str,
#                attachment_bytes: bytes | None = None,
#                attachment_name: str | None = None) -> None:
#     """Send one email via STARTTLS SMTP. Raises on failure."""
#     msg = EmailMessage()
#     msg["From"]    = _FROM_ADDRESS
#     msg["To"]      = to
#     msg["Subject"] = subject
#     msg.set_content(body)
#
#     if attachment_bytes and attachment_name:
#         msg.add_attachment(
#             attachment_bytes,
#             maintype="application",
#             subtype="pdf",
#             filename=attachment_name,
#         )
#
#     with smtplib.SMTP(_SMTP_SERVER, _SMTP_PORT) as smtp:
#         smtp.ehlo()
#         smtp.starttls()
#         smtp.login(_FROM_ADDRESS, _FROM_PASSWORD)
#         smtp.send_message(msg)


# ── Stub send (active until credentials arrive) ───────────────────────────────

def _stub_send(to: str, subject: str, body: str,
               attachment_bytes: bytes | None = None,
               attachment_name: str | None = None) -> None:
    """
    No-op stand-in for _smtp_send(). Logs what *would* be sent.
    Replace with _smtp_send() call once GT_EMAIL_ADDRESS/PASSWORD are set.
    """
    preview = body[:120].replace("\n", " ")
    print(
        f"[STUB EMAIL] To={to!r} Subject={subject!r} "
        f"Body='{preview}...' Attachment={attachment_name!r}"
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def send_quote_email(
    ref_code: str,
    quote_id: int,
    customer_email: str,
    customer_name: str,
    actor: str,
    pdf_bytes: bytes | None = None,
) -> tuple[bool, str]:
    """
    Send the proforma PDF to the client.

    Returns (True, success_message) on success.
    Returns (False, error_message) on failure.
    Always logs QUOTE_SENT (or QUOTE_SEND_FAILED) to the audit trail.
    """
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
    attachment_name = f"Proforma_{ref_code.replace(' ', '_')}.pdf" if pdf_bytes else None

    try:
        _stub_send(customer_email, subject, body, pdf_bytes, attachment_name)
        audit("QUOTE_SENT", ref_code, actor, {
            "to": customer_email,
            "customer": customer_name,
            "quote_id": quote_id,
            "stub": _STUB_MODE,
            "has_pdf": pdf_bytes is not None,
        })
        mode = "stub" if _STUB_MODE else "smtp"
        return True, f"Cotización {ref_code} enviada a {customer_email} [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("QUOTE_SEND_FAILED", ref_code, actor, {
            "to": customer_email,
            "error": error,
            "traceback": traceback.format_exc()[-500:],
        })
        return False, f"Error al enviar {ref_code}: {error}"


def send_provider_email(
    ref_code: str,
    provider: str,
    to: str,
    subject: str,
    body: str,
    actor: str,
) -> tuple[bool, str]:
    """
    Send a rate-request email to a provider/consolidator.

    Returns (True, success_message) on success.
    Returns (False, error_message) on failure.
    Always logs PROVIDER_EMAIL_SENT (or PROVIDER_EMAIL_FAILED) to the audit trail.
    """
    try:
        _stub_send(to, subject, body)
        audit("PROVIDER_EMAIL_SENT", ref_code, actor, {
            "to": to,
            "provider": provider,
            "subject": subject,
            "stub": _STUB_MODE,
        })
        mode = "stub" if _STUB_MODE else "smtp"
        return True, f"Email enviado a {provider} ({to}) [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("PROVIDER_EMAIL_FAILED", ref_code, actor, {
            "to": to,
            "provider": provider,
            "error": error,
        })
        return False, f"Error al enviar a {provider}: {error}"


def send_acknowledgment_email(
    recipient_email: str,
    recipient_name: str,
    subject: str,
    ack_text: str,
    actor: str = "system",
) -> tuple[bool, str]:
    """
    Send an auto-acknowledgment email.

    Returns (True, success_message) or (False, error_message).
    Always logs ACK_SENT (or ACK_SEND_FAILED) to the audit trail.
    """
    try:
        _stub_send(recipient_email, subject, ack_text)
        audit("ACK_SENT", None, actor, {
            "to": recipient_email,
            "recipient": recipient_name,
            "subject": subject,
            "stub": _STUB_MODE,
        })
        mode = "stub" if _STUB_MODE else "smtp"
        return True, f"Acuse enviado a {recipient_email} [{mode}]"

    except Exception as exc:
        error = str(exc)
        audit("ACK_SEND_FAILED", None, actor, {
            "to": recipient_email,
            "error": error,
        })
        return False, f"Error al enviar acuse a {recipient_email}: {error}"
