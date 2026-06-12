"""
Provider email draft generator.

Abel's format (Meeting 3, 22:10):
  "Short, professional, direct. Subject: reference code + brief description.
   Body: one paragraph — greeting, incoterm, origin, destination,
   packing list/dimensions attached. No more."

LCL  → MSL, CRAFT, SACO, VANGUARD, ECU WORLDWIDE (from providers DB)
Aéreo → LAN, American Airlines, United (from providers DB where available)
FCL  → generic naviera template

Real To: addresses come from the providers table (seeded from DATA COLOADERS.xlsx).
Falls back to provider name only (no email) when table is empty or no match.
"""

from __future__ import annotations

from string import Template

try:
    from core.providers import get_provider_emails
    _PROVIDERS_AVAILABLE = True
except Exception:
    _PROVIDERS_AVAILABLE = False

    def get_provider_emails(_company: str) -> list[str]:  # type: ignore[misc]
        return []

from config.signatures import get_signature, signature_text  # noqa: E402


# ── Provider definitions ────────────────────────────────────────────────────
# LCL providers now come from the providers DB. These are the defaults used
# for email drafts when the DB has no entries.

LCL_PROVIDERS = ["MSL", "CRAFT", "SACO", "VANGUARD", "ECU WORLDWIDE"]

AEREO_PROVIDERS = ["LAN Airlines", "American Airlines", "United Airlines"]

FCL_PROVIDERS = ["Naviera"]

# ── Email templates ─────────────────────────────────────────────────────────
# Using string.Template: $var substitution, safe_substitute for missing keys.

_SUBJECT_TMPL = Template(
    "$reference — Solicitud de tarifa $origin → $destination [$mode_label]"
)

_BODY_ES = Template("""\
Estimados señores de $provider,

Por medio de la presente, nos dirigimos a ustedes para solicitar cotización de \
flete $mode_label bajo términos $incoterm, con origen en $origin y destino \
$destination, para la siguiente mercancía:

  · Descripción : $cargo_description
  · Peso total  : $weight_kg kg
  · Volumen     : $volume_cbm CBM$dimensions_line

Agradecemos su cotización a vuelta de correo e indicar vigencia de tarifa. \
Adjuntamos packing list para su referencia.

Código de referencia para su respuesta: $reference

Atentamente,
$staff_sig\
""")

_BODY_EN = Template("""\
Dear $provider Team,

We are requesting a freight rate under $incoterm terms, from $origin to \
$destination, for the following cargo:

  · Description : $cargo_description
  · Total weight: $weight_kg kg
  · Volume      : $volume_cbm CBM$dimensions_line

Please include rate validity and any applicable surcharges. \
Packing list is attached for reference.

Please quote with reference: $reference

Best regards,
$staff_sig\
""")

# LAN / AA / United prefer English for aéreo international
_MODE_LABELS = {
    "lcl":   "LCL (carga consolidada)",
    "fcl":   "FCL (contenedor completo)",
    "aereo": "aéreo",
}


def _build_email(
    provider: str,
    quote: dict,
    language: str = "es",
) -> dict:
    """Build one email draft dict for a single provider."""
    mode       = (quote.get("mode") or "lcl").lower()
    ref        = quote.get("reference_code") or "N/A"
    origin     = quote.get("origin") or "Lima"
    dest       = quote.get("destination") or ""
    incoterm   = (quote.get("incoterm") or "FOB").upper()
    cargo_desc = quote.get("cargo_description") or "carga general"
    weight_kg  = quote.get("weight_kg") or 0.0
    cbm        = quote.get("volume_cbm") or 0.0
    staff_code = quote.get("staff_code", "")
    sig        = get_signature(staff_code)
    staff_name = sig["name"]
    staff_sig  = signature_text(staff_code)
    mode_label = _MODE_LABELS.get(mode, mode)

    # Optional dimensions line
    dims = quote.get("dimensions_json") or {}
    if isinstance(dims, str):
        import json as _json
        try:
            dims = _json.loads(dims)
        except Exception:
            dims = {}
    dim_line = ""
    if dims.get("l") and dims.get("w") and dims.get("h"):
        dim_line = f"\n  · Dimensiones : {dims['l']} × {dims['w']} × {dims['h']} cm"
        if dims.get("qty", 1) > 1:
            dim_line += f" × {dims['qty']} bultos"

    subject = _SUBJECT_TMPL.safe_substitute(
        reference=ref,
        origin=origin,
        destination=dest,
        mode_label=mode_label.upper(),
    )

    params = dict(
        provider=provider,
        reference=ref,
        origin=origin,
        destination=dest,
        incoterm=incoterm,
        cargo_description=cargo_desc,
        weight_kg=f"{weight_kg:.1f}",
        volume_cbm=f"{cbm:.4f}",
        dimensions_line=dim_line,
        mode_label=mode_label,
        staff_name=staff_name,
        staff_sig=staff_sig,
    )

    body = (_BODY_EN if language == "en" else _BODY_ES).safe_substitute(**params)

    # Look up real To: addresses from the providers DB
    to_emails = get_provider_emails(provider) if _PROVIDERS_AVAILABLE else []

    return {
        "provider":  provider,
        "subject":   subject,
        "body":      body,
        "language":  language,
        "to_emails": to_emails,  # [] when providers table empty or no match
    }


def generate_provider_emails(quote: dict) -> list[dict]:
    """
    Return one email draft per relevant provider for this quote's mode.

    LCL   → 4 drafts (MSL, Craft, Saco, EQ) in Spanish
    Aéreo → 3 drafts (LAN, AA, United) in English
    FCL   → 1 draft  (generic naviera) in Spanish
    """
    mode = (quote.get("mode") or "lcl").lower()

    if mode == "lcl":
        return [_build_email(p, quote, language="es") for p in LCL_PROVIDERS]
    elif mode == "aereo":
        return [_build_email(p, quote, language="en") for p in AEREO_PROVIDERS]
    elif mode == "fcl":
        return [_build_email("Naviera / Carrier", quote, language="es")]
    else:
        return [_build_email("Proveedor", quote, language="es")]
