"""
Auto-acknowledgment generator — Pipeline #3 Step 1 (free kicker).

"Every incoming quote request (any language, any hour) gets an instant
intelligent acknowledgment in sender's language."

Languages: ES, EN, DE, ZH, FR, PT
Content: receipt confirmation + cargo subject + ETA + reference
NOT included: PDFs, quotes, costeo, any pricing
"""

from __future__ import annotations

from string import Template

# ── Templates (one per language) ─────────────────────────────────────────────

_TEMPLATES: dict[str, str] = {
    "es": (
        "Estimado/a $client,\n\n"
        "Hemos recibido su solicitud de cotización para $cargo_summary.\n\n"
        "Nuestro equipo comercial revisará los detalles y le enviará nuestra "
        "propuesta en las próximas $response_hours horas.\n\n"
        "Código de referencia: $reference\n\n"
        "Muchas gracias por contactar a Global Transport SAC.\n\n"
        "Atentamente,\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
    "en": (
        "Dear $client,\n\n"
        "We have received your quotation request for $cargo_summary.\n\n"
        "Our commercial team will review the details and send you our proposal "
        "within the next $response_hours hours.\n\n"
        "Reference: $reference\n\n"
        "Thank you for contacting Global Transport SAC.\n\n"
        "Best regards,\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
    "de": (
        "Sehr geehrte/r $client,\n\n"
        "wir haben Ihre Angebotsanfrage für $cargo_summary erhalten.\n\n"
        "Unser Vertriebsteam wird die Details prüfen und Ihnen innerhalb der "
        "nächsten $response_hours Stunden unser Angebot zusenden.\n\n"
        "Referenz: $reference\n\n"
        "Vielen Dank, dass Sie Global Transport SAC kontaktiert haben.\n\n"
        "Mit freundlichen Grüßen,\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
    "zh": (
        "尊敬的 $client，\n\n"
        "我们已收到您关于 $cargo_summary 的询价请求。\n\n"
        "我们的商务团队将审核相关信息，并在 $response_hours 小时内向您发送报价。\n\n"
        "参考编号：$reference\n\n"
        "感谢您联系 Global Transport SAC。\n\n"
        "此致，\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
    "fr": (
        "Cher/Chère $client,\n\n"
        "Nous avons bien reçu votre demande de cotation pour $cargo_summary.\n\n"
        "Notre équipe commerciale examinera les détails et vous enverra notre "
        "offre dans les $response_hours prochaines heures.\n\n"
        "Référence : $reference\n\n"
        "Merci de nous avoir contactés chez Global Transport SAC.\n\n"
        "Cordialement,\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
    "pt": (
        "Prezado/a $client,\n\n"
        "Recebemos sua solicitação de cotação para $cargo_summary.\n\n"
        "Nossa equipe comercial analisará os detalhes e enviará nossa proposta "
        "nas próximas $response_hours horas.\n\n"
        "Referência: $reference\n\n"
        "Obrigado por entrar em contato com a Global Transport SAC.\n\n"
        "Atenciosamente,\n"
        "$staff_name\n"
        "Global Transport SAC"
    ),
}

SUPPORTED_LANGUAGES: list[str] = list(_TEMPLATES.keys())


def generate_acknowledgment(
    language: str,
    client: str,
    cargo_summary: str,
    reference: str,
    staff_name: str = "Equipo Comercial",
    response_hours: int = 4,
) -> str:
    """
    Return the acknowledgment text in the requested language.
    Falls back to Spanish ('es') if language is not supported.

    Args:
        language:      ISO 639-1 code (es/en/de/zh/fr/pt)
        client:        Sender name or company
        cargo_summary: Brief cargo description from the parsed request
        reference:     Generated reference code
        staff_name:    Signing staff member name
        response_hours: Estimated response time
    """
    lang = language.lower()
    if lang not in _TEMPLATES:
        lang = "es"

    tmpl = Template(_TEMPLATES[lang])
    return tmpl.safe_substitute(
        client=client,
        cargo_summary=cargo_summary,
        reference=reference,
        staff_name=staff_name,
        response_hours=response_hours,
    )


def supported_languages() -> list[str]:
    return SUPPORTED_LANGUAGES


# ── Subject lines (one per language) ─────────────────────────────────────────

_SUBJECTS: dict[str, str] = {
    "es": "Acuse de recibo — solicitud de cotización Global Transport SAC",
    "en": "Acknowledgment — quotation request Global Transport SAC",
    "de": "Eingangsbestätigung — Angebotsanfrage Global Transport SAC",
    "zh": "收到确认 — 报价请求 Global Transport SAC",
    "fr": "Accusé de réception — demande de cotation Global Transport SAC",
    "pt": "Acuse de recebimento — solicitação de cotação Global Transport SAC",
}

# ── Stub mode — no API key needed for testing/demo ───────────────────────────

_ACK_STUB_MODE = not __import__("os").getenv("ANTHROPIC_API_KEY")


def generate_acknowledgment_from_request(parsed_request: dict) -> dict:
    """
    Generate an acknowledgment for an inbound quote request.

    Uses Claude API (claude-sonnet-4-20250514) when ANTHROPIC_API_KEY is set.
    Falls back to template-based generation when key is absent (same result quality
    for demo — the templates are already professional and multilingual).

    Args:
        parsed_request: Dict from email_listener.parse_quote_request()

    Returns:
        {
            "subject":        str,  # email subject in detected language
            "body":           str,  # acknowledgment body in detected language
            "language":       str,  # ISO 639-1 code
            "detected_topic": str,  # brief English description of inquiry
        }
    """
    lang            = (parsed_request.get("detected_language") or "es").lower()
    customer_name   = parsed_request.get("customer_name") or "Cliente"
    service_type    = parsed_request.get("service_type") or "carga"
    origin          = parsed_request.get("origin_city") or ""
    destination     = parsed_request.get("destination_city") or ""
    commodity       = parsed_request.get("commodity") or ""
    direction       = parsed_request.get("direction") or ""
    urgency         = parsed_request.get("urgency") or "flexible"

    # Build cargo summary for template
    parts = []
    if service_type and service_type != "unknown":
        parts.append(service_type)
    if commodity:
        parts.append(commodity)
    if origin and destination:
        parts.append(f"{origin} → {destination}")
    cargo_summary = " · ".join(parts) if parts else "su carga"

    # English topic for internal use
    detected_topic = (
        f"{service_type} freight"
        + (f" — {commodity}" if commodity else "")
        + (f" from {origin}" if origin else "")
        + (f" to {destination}" if destination else "")
    ).strip(" —")

    # Response hours: 2h if asap, 4h otherwise (GT business hours)
    response_hours = 2 if urgency == "asap" else 4

    if not _ACK_STUB_MODE:
        body = _live_ack(lang, customer_name, cargo_summary, response_hours,
                         detected_topic, parsed_request)
    else:
        body = generate_acknowledgment(
            language=lang,
            client=customer_name,
            cargo_summary=cargo_summary,
            reference="—",  # No reference at acknowledgment stage
            staff_name="El equipo comercial de Global Transport",
            response_hours=response_hours,
        )

    subject = _SUBJECTS.get(lang, _SUBJECTS["es"])

    return {
        "subject":        subject,
        "body":           body,
        "language":       lang,
        "detected_topic": detected_topic,
    }


def _live_ack(
    lang: str,
    customer_name: str,
    cargo_summary: str,
    response_hours: int,
    detected_topic: str,
    parsed_request: dict,
) -> str:
    """
    Generate acknowledgment via Claude API.
    Falls back to template silently on any error.
    """
    import anthropic  # noqa: PLC0415

    system = (
        "You are the commercial team of Global Transport SAC, a professional freight "
        "forwarder in Lima, Peru. Write a brief acknowledgment email in the EXACT language "
        f"specified (ISO code: {lang}). "
        "Rules: "
        "3-4 sentences maximum. "
        "Reference the specific cargo/service. "
        "Give the estimated response time. "
        "Sign as 'El equipo comercial de Global Transport'. "
        "Professional and warm tone. "
        "Do NOT mention any rates, prices, or commitments. "
        "Return ONLY the email body text, no subject line, no extra formatting."
    )
    user_prompt = (
        f"Write an acknowledgment for this freight inquiry:\n"
        f"- Customer: {customer_name}\n"
        f"- Service: {detected_topic}\n"
        f"- Cargo summary: {cargo_summary}\n"
        f"- Response time: {response_hours} hours\n"
        f"- Language: {lang}"
    )
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        # Silent fallback to template
        return generate_acknowledgment(
            language=lang,
            client=customer_name,
            cargo_summary=cargo_summary,
            reference="—",
            staff_name="El equipo comercial de Global Transport",
            response_hours=response_hours,
        )


def detect_and_acknowledge(
    raw_text: str,
    staff_name: str = "El equipo comercial de Global Transport",
    response_hours: int | None = None,
) -> dict:
    """
    Single-call pipeline: raw message text → acknowledgment dict.

    Detects the language, extracts cargo subject, and generates an
    acknowledgment in the same language as the sender.

    This is the entry point for wiring acknowledgments into the inbound
    email listener. It does NOT require the email to be fully parsed first.

    Args:
        raw_text:       Raw email or WhatsApp message body.
        staff_name:     Name to sign the acknowledgment with.
        response_hours: Override SLA hours; if None, auto-detects from urgency.

    Returns:
        {
            "subject":        str,   # email subject in detected language
            "body":           str,   # acknowledgment body
            "language":       str,   # ISO 639-1 code (es/en/de/zh/fr/pt)
            "detected_topic": str,   # brief English cargo description
            "response_hours": int,   # SLA hours used
        }
    """
    from core.parser import detect_language, detect_mode, parse_incoterm  # noqa: PLC0415

    # Detect language from raw text
    lang = detect_language(raw_text)

    # Extract cargo / service info from raw text
    mode       = detect_mode(raw_text) or "cargo"
    incoterm   = parse_incoterm(raw_text)
    text_lower = raw_text.lower()

    # Quick client name heuristic: first proper noun after greeting
    client = "Cliente"
    for line in raw_text.split("\n"):
        line = line.strip()
        if any(g in line.lower() for g in ["my name is", "mi nombre es", "ich bin",
                                            "je suis", "我是", "sou"]):
            # "My name is Sarah Johnson from …" → take first two words after greeting
            parts = line.split()
            for i, p in enumerate(parts):
                if p.lower() in ("is", "es", "bin", "suis"):
                    candidate = " ".join(parts[i + 1: i + 3])
                    if candidate:
                        client = candidate
                    break
            break

    # Build cargo summary
    parts = []
    if mode and mode != "cargo":
        parts.append(mode.upper() if mode in ("lcl", "fcl") else mode)
    if incoterm:
        parts.append(incoterm)

    # Route description: look for origin→destination markers
    origin = dest = ""
    for kw in ["from ", "desde ", "von ", "de "]:
        idx = text_lower.find(kw)
        if idx != -1:
            snippet = raw_text[idx + len(kw): idx + len(kw) + 30].split("\n")[0].split(",")[0].strip()
            if snippet:
                origin = snippet
            break
    for kw in ["to ", "hacia ", "nach ", "à ", "to\n"]:
        idx = text_lower.find(kw)
        if idx != -1:
            snippet = raw_text[idx + len(kw): idx + len(kw) + 30].split("\n")[0].split(",")[0].strip()
            if snippet:
                dest = snippet
            break

    if origin and dest:
        parts.append(f"{origin} → {dest}")

    cargo_summary = " · ".join(parts) if parts else "su consulta de carga"

    # Urgency → SLA
    is_urgent = any(w in text_lower for w in [
        "urgent", "urgente", "dringend", "asap", "dringend", "urgent",
        "lo antes posible", "inmediato", "sofort",
    ])
    sla = response_hours if response_hours is not None else (2 if is_urgent else 4)

    # Detected topic (English, for internal use)
    detected_topic = (
        f"{mode} freight"
        + (f" · {incoterm}" if incoterm else "")
        + (f" · {origin} → {dest}" if origin and dest else "")
    )

    body = generate_acknowledgment(
        language=lang,
        client=client,
        cargo_summary=cargo_summary,
        reference="—",
        staff_name=staff_name,
        response_hours=sla,
    )

    return {
        "subject":        _SUBJECTS.get(lang, _SUBJECTS["es"]),
        "body":           body,
        "language":       lang,
        "detected_topic": detected_topic.strip(" ·"),
        "response_hours": sla,
    }


def send_acknowledgment(parsed_request: dict, ack: dict) -> tuple[bool, str]:
    """
    Send an acknowledgment email using core/email_sender (stub until SMTP credentials land).

    Args:
        parsed_request: Output of email_listener.parse_quote_request()
        ack:            Output of generate_acknowledgment_from_request()

    Returns:
        (success: bool, message: str)
    """
    from core.email_sender import send_acknowledgment_email  # noqa: PLC0415
    from core.db import audit as _audit  # noqa: PLC0415

    recipient_email = parsed_request.get("customer_email") or ""
    recipient_name  = parsed_request.get("customer_name") or "Cliente"
    subject         = ack.get("subject", "Acuse de recibo")
    body            = ack.get("body", "")
    lang            = ack.get("language", "es")
    topic           = ack.get("detected_topic", "")

    ok, msg = send_acknowledgment_email(
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        ack_text=body,
        actor="email_listener",
    )

    _audit(
        "ACK_SENT" if ok else "ACK_SEND_FAILED",
        None,
        "email_listener",
        {
            "recipient_email": recipient_email,
            "language":        lang,
            "detected_topic":  topic,
            "message":         msg,
        },
    )
    return ok, msg
