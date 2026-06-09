"""
Provider reply parser — closes the rate-collection leg of the cotizador pipeline.

When a provider (MSL, Craft, LAN, etc.) replies to a rate request email, this
module:
  1. Detects the reply by reference-code pattern in subject (or known sender domain)
  2. Identifies the provider from the sender email address
  3. Extracts freight rates via Claude API (or keyword stub when key absent)
  4. Stores the parsed reply in the provider_replies table
  5. Updates the quote's costeo_json with the cheapest flete seen so far
  6. Logs PROVIDER_REPLY_RECEIVED, PROVIDER_RATE_PARSED (or PARSE_FAILED), RATES_READY

All functions are safe to call in stub mode (no ANTHROPIC_API_KEY required).

Expected provider counts per mode (used to determine when all have replied):
  LCL   → 5  (MSL, CRAFT, SACO, VANGUARD, ECU WORLDWIDE)
  aereo → 3  (LAN Airlines, American Airlines, United Airlines)
  FCL   → 1  (generic naviera)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from core.db import (
    audit,
    get_connection,
    get_provider_replies,
    store_provider_reply,
    update_quote_flete,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_STUB_MODE = not os.getenv("ANTHROPIC_API_KEY")

# Reference code pattern: YY-MM-NNN  (e.g. 26-06-001)
REFERENCE_PATTERN = re.compile(r"\b(\d{2}-\d{2}-\d{3})\b")

# Expected provider counts per quote mode
_EXPECTED_PROVIDERS: dict[str, int] = {
    "lcl":   5,
    "aereo": 3,
    "fcl":   1,
}

# Known provider domain fragments → canonical name.  Checked in order; first match wins.
_DOMAIN_MAP: list[tuple[str, str]] = [
    ("mslcorporate", "MSL"),
    ("msl.com",      "MSL"),
    ("msl.pe",       "MSL"),
    ("craft.com",    "CRAFT"),
    ("craft.pe",     "CRAFT"),
    ("saco.com",     "SACO"),
    ("saco.pe",      "SACO"),
    ("vanguardlogistics", "VANGUARD"),
    ("vanguard.pe",  "VANGUARD"),
    ("ecuwoorldwide", "ECU WORLDWIDE"),
    ("ecuworldwide", "ECU WORLDWIDE"),
    ("ecu.pe",       "ECU WORLDWIDE"),
    ("latamairlines", "LAN Airlines"),
    ("lan.com",      "LAN Airlines"),
    ("tam.com",      "LAN Airlines"),
    ("aa.com",       "American Airlines"),
    ("americanairlines", "American Airlines"),
    ("united.com",   "United Airlines"),
    ("unitedairlines", "United Airlines"),
]

# ── Detection ─────────────────────────────────────────────────────────────────

def is_provider_reply(email: dict) -> bool:
    """
    Return True if this email looks like a provider rate reply rather than a
    new client request.

    Detection rules (either is sufficient):
      1. Subject contains a GT reference code (YY-MM-NNN)
      2. Sender email matches a known provider domain
    """
    subject = (email.get("subject") or "").lower()
    sender  = (email.get("from")    or "").lower()

    if REFERENCE_PATTERN.search(subject):
        return True
    if _is_known_provider_email(sender):
        return True
    return False


def _is_known_provider_email(email_addr: str) -> bool:
    domain = email_addr.split("@")[-1] if "@" in email_addr else email_addr
    return any(frag in domain for frag, _ in _DOMAIN_MAP)


# ── Reference extraction ──────────────────────────────────────────────────────

def extract_reference_from_subject(subject: str) -> str | None:
    """Return the first GT reference code found in the subject, or None."""
    m = REFERENCE_PATTERN.search(subject or "")
    return m.group(1) if m else None


# ── Provider identification ───────────────────────────────────────────────────

def identify_provider(sender_email: str, email_body: str = "") -> str:
    """
    Identify the provider by:
      1. Exact or domain match in the providers DB
      2. Known domain pattern list
      3. Email domain heuristic → DB partial company lookup
      4. Fallback: "Unknown Provider"
    """
    sender = (sender_email or "").strip().lower()

    db_name = _db_lookup_by_email(sender)
    if db_name:
        return db_name

    domain = sender.split("@")[-1] if "@" in sender else sender
    for frag, name in _DOMAIN_MAP:
        if frag in domain:
            return name

    company_guess = domain.split(".")[0].upper() if "." in domain else domain.upper()
    if company_guess:
        db_name = _db_lookup_by_company(company_guess)
        if db_name:
            return db_name

    return "Unknown Provider"


def _db_lookup_by_email(email_addr: str) -> str | None:
    if not email_addr:
        return None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT company FROM providers WHERE LOWER(email) LIKE ? AND active=1 LIMIT 1",
                (f"%{email_addr}%",),
            ).fetchone()
            if row:
                return row["company"]
            if "@" in email_addr:
                domain = email_addr.split("@")[1]
                row = conn.execute(
                    "SELECT company FROM providers WHERE LOWER(email) LIKE ? AND active=1 LIMIT 1",
                    (f"%@{domain}%",),
                ).fetchone()
                if row:
                    return row["company"]
    except Exception:
        pass
    return None


def _db_lookup_by_company(fragment: str) -> str | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT company FROM providers WHERE UPPER(company) LIKE ? AND active=1 LIMIT 1",
                (f"%{fragment}%",),
            ).fetchone()
        return row["company"] if row else None
    except Exception:
        return None


# ── Rate extraction ───────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """\
You are a freight-rate extraction specialist for Global Transport SAC, Lima, Peru.
Parse a provider's rate reply email and extract the quoted freight rates.
Return ONLY a JSON object with these fields:
  flete_usd        (number or null — international freight charge in USD)
  visto_bueno_usd  (number or null — BL fee / visto bueno / documentation fee in USD)
  transit_days     (integer or null — transit time in days)
  validity_days    (integer or null — rate validity in days)
  currency         (string — e.g. "USD", "EUR"; default "USD")
  surcharges       (array of {name: string, amount: number, currency: string})
  notes            (string or null — caveats, restrictions, conditions)

Rules:
- Extract numbers only — never invent figures.
- If a value cannot be determined, use null.
- Common Spanish terms: flete, tarifa, visto bueno, tránsito, vigencia, recargo, sobretasa.
- Common English terms: freight, B/L fee, transit time, validity, surcharge, THC, BAF, CAF.
"""


def parse_provider_reply(raw_body: str, provider_name: str = "") -> dict:
    """
    Extract rate data from a raw provider reply email body.
    Uses Claude API when ANTHROPIC_API_KEY is set; falls back to regex stub.
    Returns: flete_usd, visto_bueno_usd, transit_days, validity_days, currency,
             surcharges_json, notes, parse_status, raw_extract_json, needs_manual_review.
    """
    if _STUB_MODE:
        return _stub_parse(raw_body)
    return _live_parse(raw_body)


def _live_parse(raw_body: str) -> dict:
    import anthropic  # noqa: PLC0415
    client = anthropic.Anthropic()
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=_EXTRACT_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    "Extract the freight rate data from this provider reply:\n\n"
                    + raw_body[:3000]
                ),
            }],
        )
        raw_json = msg.content[0].text.strip()
        if raw_json.startswith("```"):
            raw_json = "\n".join(raw_json.split("\n")[1:-1])
        parsed = json.loads(raw_json)
        surcharges = parsed.get("surcharges") or []
        return {
            "flete_usd":           _safe_float(parsed.get("flete_usd")),
            "visto_bueno_usd":     _safe_float(parsed.get("visto_bueno_usd")),
            "transit_days":        _safe_int(parsed.get("transit_days")),
            "validity_days":       _safe_int(parsed.get("validity_days")),
            "currency":            str(parsed.get("currency") or "USD"),
            "surcharges_json":     json.dumps(surcharges, ensure_ascii=False),
            "notes":               parsed.get("notes"),
            "parse_status":        "parsed",
            "raw_extract_json":    raw_json,
            "needs_manual_review": False,
        }
    except Exception as exc:
        return {
            "flete_usd": None, "visto_bueno_usd": None,
            "transit_days": None, "validity_days": None,
            "currency": "USD", "surcharges_json": "[]",
            "notes": f"Parse error: {exc}",
            "parse_status": "parse_failed",
            "raw_extract_json": None,
            "needs_manual_review": True,
        }


def _stub_parse(raw_body: str) -> dict:
    """
    Keyword/regex extraction — no API key needed.
    Handles common Spanish/English patterns in provider replies.
    """
    text = raw_body or ""

    flete = _extract_amount(text, [
        r"flete[^\d]{0,30}([\d,\.]+)",
        r"tarifa[^\d]{0,30}([\d,\.]+)",
        r"freight[^\d]{0,30}([\d,\.]+)",
        r"rate[^\d]{0,15}([\d,\.]+)",
        r"usd\s*([\d,\.]+)",
        r"\$([\d,\.]+)",
    ])
    vb = _extract_amount(text, [
        r"visto\s*bueno[^\d]{0,20}([\d,\.]+)",
        r"b/?l\s*fee[^\d]{0,20}([\d,\.]+)",
        r"bl\s+fee[^\d]{0,20}([\d,\.]+)",
        r"documentation[^\d]{0,20}([\d,\.]+)",
        r"v\.b\.[^\d]{0,10}([\d,\.]+)",
    ])
    transit = _extract_int(text, [
        r"tr[aá]nsito[^\d]{0,15}(\d+)\s*d[ií]as?",
        r"transit\s+time[^\d]{0,15}(\d+)\s*days?",
        r"(\d+)\s*d[ií]as?\s+de\s+tr[aá]nsito",
        r"eta[^\d]{0,15}(\d+)\s*days?",
        r"transit[^\d]{0,15}(\d+)",
    ])
    validity = _extract_int(text, [
        r"vigencia[^\d]{0,15}(\d+)\s*d[ií]as?",
        r"validez[^\d]{0,15}(\d+)\s*d[ií]as?",
        r"v[aá]lido[^\d]{0,15}(\d+)\s*d[ií]as?",
        r"validity[^\d]{0,15}(\d+)\s*days?",
        r"valid\s+for[^\d]{0,10}(\d+)\s*days?",
        r"(\d+)\s*d[ií]as?\s+de\s+vigencia",
    ])

    currency = "USD"
    if re.search(r"\beur\b|\b€\b", text, re.IGNORECASE):
        currency = "EUR"

    parsed = flete is not None or vb is not None or transit is not None

    return {
        "flete_usd":           flete,
        "visto_bueno_usd":     vb,
        "transit_days":        transit,
        "validity_days":       validity,
        "currency":            currency,
        "surcharges_json":     "[]",
        "notes":               None,
        "parse_status":        "parsed" if parsed else "parse_failed",
        "raw_extract_json":    None,
        "needs_manual_review": not parsed,
    }


# ── Regex helpers ─────────────────────────────────────────────────────────────

def _extract_amount(text: str, patterns: list[str]) -> float | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                if 1.0 <= val <= 99_999.0:
                    return round(val, 2)
            except ValueError:
                pass
    return None


def _extract_int(text: str, patterns: list[str]) -> int | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = int(m.group(1))
                if 0 < val < 365:
                    return val
            except ValueError:
                pass
    return None


def _safe_float(v: Any) -> float | None:
    try:
        return round(float(v), 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Expected-providers check ──────────────────────────────────────────────────

def _expected_provider_count(quote_ref: str) -> int:
    """Look up the quote's mode and return the expected number of provider replies."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT mode FROM quotes WHERE reference_code = ?", (quote_ref,)
            ).fetchone()
        if row:
            return _EXPECTED_PROVIDERS.get((row["mode"] or "").lower(), 1)
    except Exception:
        pass
    return 1


def check_rates_ready(quote_ref: str) -> bool:
    """
    Return True when distinct providers with parse_status='parsed' equals or
    exceeds the expected count for this quote's mode.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT provider_name) AS n
                   FROM provider_replies
                   WHERE quote_reference = ? AND parse_status = 'parsed'""",
                (quote_ref,),
            ).fetchone()
        received = row["n"] if row else 0
    except Exception:
        return False
    return received >= _expected_provider_count(quote_ref)


# ── Full pipeline ─────────────────────────────────────────────────────────────

def process_provider_reply(email: dict) -> dict:
    """
    Run the full provider-reply pipeline for one email dict.

    Steps:
      1. Extract reference code from subject
      2. Identify provider from sender
      3. Log PROVIDER_REPLY_RECEIVED
      4. Parse rates (Claude or stub)
      5. Store in provider_replies table
      6. Log PROVIDER_RATE_PARSED or PARSE_FAILED
      7. Update quote costeo_json with best (lowest) flete if parse succeeded
      8. Check if all expected providers replied → log RATES_READY

    Returns result dict with extracted data; metadata keys prefixed with _
    """
    result: dict = {
        "_email_type":    "provider_reply",
        "_email_id":      email.get("id"),
        "_email_from":    email.get("from"),
        "_email_subject": email.get("subject"),
        "_received_at":   email.get("received_at"),
    }

    quote_ref     = extract_reference_from_subject(email.get("subject", ""))
    provider_name = identify_provider(email.get("from", ""), email.get("body", ""))
    result["quote_reference"] = quote_ref
    result["provider_name"]   = provider_name

    audit(
        "PROVIDER_REPLY_RECEIVED",
        quote_ref,
        "email_listener",
        {
            "provider_name": provider_name,
            "sender_email":  email.get("from"),
            "subject":       email.get("subject"),
            "stub_mode":     _STUB_MODE,
        },
    )

    if not quote_ref:
        result["parse_status"]        = "parse_failed"
        result["_needs_manual_review"] = True
        audit(
            "PARSE_FAILED",
            None,
            "email_listener",
            {
                "reason":        "no_reference_code",
                "provider_name": provider_name,
                "sender_email":  email.get("from"),
            },
        )
        return result

    # Extract rates
    parsed = parse_provider_reply(email.get("body", ""), provider_name)
    result.update(parsed)

    # Persist
    reply_id = store_provider_reply({
        "quote_reference": quote_ref,
        "provider_name":   provider_name,
        "sender_email":    email.get("from"),
        "email_subject":   email.get("subject"),
        "email_body":      email.get("body"),
        **parsed,
    })
    result["_reply_db_id"] = reply_id

    parse_status = parsed.get("parse_status", "parse_failed")

    if parse_status == "parsed":
        audit(
            "PROVIDER_RATE_PARSED",
            quote_ref,
            "email_listener",
            {
                "provider_name":   provider_name,
                "flete_usd":       parsed.get("flete_usd"),
                "visto_bueno_usd": parsed.get("visto_bueno_usd"),
                "transit_days":    parsed.get("transit_days"),
                "validity_days":   parsed.get("validity_days"),
                "reply_db_id":     reply_id,
            },
        )
        if parsed.get("flete_usd") is not None:
            _apply_best_rate_to_quote(
                quote_ref, parsed["flete_usd"], parsed.get("visto_bueno_usd")
            )

    else:
        audit(
            "PARSE_FAILED",
            quote_ref,
            "email_listener",
            {
                "provider_name":  provider_name,
                "sender_email":   email.get("from"),
                "manual_review":  True,
                "raw_snippet":    (email.get("body") or "")[:400],
            },
        )
        result["_needs_manual_review"] = True

    # Check if all expected providers have replied
    if check_rates_ready(quote_ref):
        replies = get_provider_replies(quote_ref)
        audit(
            "RATES_READY",
            quote_ref,
            "email_listener",
            {
                "provider_count": len(replies),
                "providers":      [r["provider_name"] for r in replies],
                "cheapest_flete": replies[0]["flete_usd"] if replies else None,
            },
        )
        result["_rates_ready"] = True

    return result


def _apply_best_rate_to_quote(
    quote_ref: str, new_flete: float, new_vb: float | None
) -> None:
    """
    Update the quote's costeo_json flete only if the new rate is lower than current.
    Logs QUOTE_FLETE_UPDATED to audit trail on change.
    Never raises — cost update failure must not block the pipeline.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code = ?",
                (quote_ref,),
            ).fetchone()
        if not row:
            return
        costeo = json.loads(row["costeo_json"] or "{}")
        current_flete = costeo.get("flete_internacional_usd")
        # Treat 0.0 or None as "no rate set" — any positive rate from a provider should win
        no_rate_yet = current_flete is None or current_flete <= 0
        if no_rate_yet or new_flete < current_flete:
            update_quote_flete(quote_ref, new_flete, new_vb)
            audit(
                "QUOTE_FLETE_UPDATED",
                quote_ref,
                "email_listener",
                {
                    "previous_flete_usd": current_flete,
                    "new_flete_usd":      new_flete,
                    "new_vb_usd":         new_vb,
                },
            )
    except Exception:
        pass
