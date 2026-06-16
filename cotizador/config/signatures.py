"""
GT Cotizador — Staff signature registry.

Maps staff codes (GT-PC, GT-WCA, GT-LOG) and person keys to full contact
blocks used in outbound emails, PDF proformas, and acknowledgments.

Address shared by all staff:
  Av. Mariscal La Mar N° 662, of. 605 - 606. Miraflores, LIMA, PERÚ
"""

from __future__ import annotations

_GT_ADDRESS = "Av. Mariscal La Mar N° 662, of. 605 - 606. Miraflores, LIMA, PERÚ"
_GT_WEBSITE = "www.gt.com.pe"

# ── Signature records ─────────────────────────────────────────────────────────

_SIGNATURES: dict[str, dict] = {
    # ── Quote staff (keyed by staff_code) ─────────────────────────────────────
    "GT-PC": {
        "name":    "Abel Díaz Peralta",
        "title":   "Commercial Leader",
        "phone":   "(+51) 983 421 482",
        "email":   "pricing@gt.com.pe",
        "address": _GT_ADDRESS,
        "website": _GT_WEBSITE,
    },
    "GT-WCA": {
        "name":    "Cielo Cuellar",
        "title":   "WCA Sales",
        "phone":   "(+51) 923 098 958",
        "email":   "wca.sales@gt.com.pe",
        "address": _GT_ADDRESS,
        "website": _GT_WEBSITE,
    },
    "GT-LOG": {
        "name":    "Daniella Leveau",
        "title":   "Lognet Sales",
        "phone":   "(+51) 923 098 958",
        "email":   "lognet.sales@gt.com.pe",
        "address": _GT_ADDRESS,
        "website": _GT_WEBSITE,
    },
    # ── Management (used for approvals, cover letters, escalations) ────────────
    "RENATO": {
        "name":    "Renato Alvarez",
        "title":   "General Manager",
        "phone":   "(+51) 998 348 636",
        "email":   "ralvarez@gt.com.pe",
        "address": _GT_ADDRESS,
        "website": _GT_WEBSITE,
    },
    "JP": {
        "name":    "Jean Paul Arrue",
        "title":   "Executive Director",
        "phone":   "(+51) 994 158 380",
        "email":   "jparrue@gt.com.pe",
        "address": _GT_ADDRESS,
        "website": _GT_WEBSITE,
    },
}

# ── Fallback when code is unknown ─────────────────────────────────────────────
_DEFAULT: dict = {
    "name":    "Equipo Comercial",
    "title":   "Global Transport SAC",
    "phone":   "",
    "email":   "comercial@globaltransportperu.com",
    "address": _GT_ADDRESS,
    "website": _GT_WEBSITE,
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_signature(staff_code: str) -> dict:
    """
    Return the signature dict for a given staff_code (or person key).
    Falls back to the generic commercial signature if code is unknown.

    Keys: name, title, phone, email, address, website
    """
    return _SIGNATURES.get((staff_code or "").strip().upper(), _DEFAULT)


def signature_text(staff_code: str) -> str:
    """
    Return a formatted plain-text signature block for use in email bodies.

    Format:
        Name
        Title
        Address
        Phone / email
        website
    """
    sig = get_signature(staff_code)
    lines = [
        sig["name"],
        sig["title"],
        sig["address"],
    ]
    if sig["phone"] and sig["email"]:
        lines.append(f"{sig['phone']} / {sig['email']}")
    elif sig["email"]:
        lines.append(sig["email"])
    if sig["website"]:
        lines.append(sig["website"])
    return "\n".join(lines)


def all_staff_codes() -> list[str]:
    """Return all registered staff codes (excludes management-only keys)."""
    return [k for k in _SIGNATURES if k.startswith("GT-")]
