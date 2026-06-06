"""
Email / WhatsApp request parser.

Extracts: language, incoterm, mode (aereo/lcl/fcl), weight, volume/CBM,
dimensions, origin, destination, cargo description.

Abel reads the email and identifies: incoterm, import/export direction,
FCL/LCL/aéreo, cargo classification. This module automates that step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Language detection ────────────────────────────────────────────────────────
# Keyword-vote approach. Falls back to "es" (Spanish).

_LANG_KEYWORDS: dict[str, list[str]] = {
    "de": ["sehr geehrte", "bitte", "absender", "gewicht", "fracht",
           "sendung", "bestellung", "anfrage", "lieferung"],
    "zh": ["您好", "重量", "货物", "发件人", "询价", "运输", "报价", "集装箱"],
    "fr": ["monsieur", "madame", "veuillez", "expéditeur", "poids",
           "fret", "marchandise", "envoi", "cotation"],
    "pt": ["prezado", "prezada", "peso", "carga", "remetente",
           "cotação", "frete", "envio", "mercadoria"],
    "en": ["dear", "please", "shipper", "weight", "freight", "cargo",
           "kindly", "quotation", "shipment", "container"],
    "es": ["estimado", "estimada", "peso", "carga", "remitente",
           "cotización", "por favor", "flete", "embarque", "mercancía"],
}

# ── Regex patterns ────────────────────────────────────────────────────────────

_INCOTERM_RE = re.compile(
    r'\b(EXW|FCA|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b', re.IGNORECASE
)

_WEIGHT_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(kg|kgs?|kilogram(?:s)?|lb|lbs?|pound(?:s)?)',
    re.IGNORECASE,
)

_CBM_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(?:cbm|m3|m³|cubic\s*met(?:er|re)s?)',
    re.IGNORECASE,
)

# L × W × H with optional unit suffix
_DIM_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)'
    r'(?:\s*(cm|in(?:ch(?:es)?)?|m(?:eters?|etres?)?))?',
    re.IGNORECASE,
)

_MODE_KEYWORDS: dict[str, list[str]] = {
    "aereo": ["aereo", "aéreo", "air", "air freight", "aérien",
              "luftfracht", "航空", "flete aéreo"],
    "lcl":   ["lcl", "carga suelta", "consolidado", "less than container",
              "groupage", "groupaje", "loose cargo"],
    "fcl":   ["fcl", "contenedor", "full container", "full container load",
              "container completo", "fcl cargo"],
}


def _clean_float(s: str) -> float:
    return float(s.replace(",", "."))


# ── Public API ────────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Return ISO 639-1 language code. Falls back to 'es'."""
    lower = text.lower()
    scores: dict[str, int] = {lang: 0 for lang in _LANG_KEYWORDS}
    for lang, keywords in _LANG_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                scores[lang] += 1
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] > 0 else "es"


def detect_mode(text: str) -> str | None:
    lower = text.lower()
    for mode, keywords in _MODE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return mode
    return None


def parse_incoterm(text: str) -> str | None:
    m = _INCOTERM_RE.search(text)
    return m.group(1).upper() if m else None


def parse_weight_kg(text: str) -> float | None:
    """Return weight in kg, converting lbs if needed."""
    from core.units import lbs_to_kg
    m = _WEIGHT_RE.search(text)
    if not m:
        return None
    value = _clean_float(m.group(1))
    unit = m.group(2).lower()
    if "lb" in unit or "pound" in unit:
        return lbs_to_kg(value)
    return value


def parse_cbm(text: str) -> float | None:
    m = _CBM_RE.search(text)
    return _clean_float(m.group(1)) if m else None


def parse_dimensions(text: str) -> dict | None:
    """Return {l, w, h, unit} if L×W×H pattern found, else None."""
    m = _DIM_RE.search(text)
    if not m:
        return None
    unit = (m.group(4) or "cm").lower()
    if unit.startswith("in"):
        unit = "in"
    elif unit.startswith("m") and "cm" not in unit:
        unit = "m"
    else:
        unit = "cm"
    return {
        "l": _clean_float(m.group(1)),
        "w": _clean_float(m.group(2)),
        "h": _clean_float(m.group(3)),
        "unit": unit,
        "raw": m.group(0),
    }


@dataclass
class ParsedRequest:
    raw_text: str
    language: str = "es"
    incoterm: str | None = None
    mode: str | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    dimensions: dict | None = None
    origin: str | None = None
    destination: str | None = None
    client_name: str | None = None
    cargo_description: str | None = None
    confidence: float = 0.0    # 0–1 based on how many fields were extracted


def parse_request(text: str) -> ParsedRequest:
    """Parse an inbound email or WhatsApp message into structured fields."""
    result = ParsedRequest(raw_text=text)
    result.language = detect_language(text)
    result.incoterm = parse_incoterm(text)
    result.mode = detect_mode(text)
    result.weight_kg = parse_weight_kg(text)
    result.volume_cbm = parse_cbm(text)
    result.dimensions = parse_dimensions(text)

    # Confidence: ratio of key fields successfully extracted
    extracted = sum([
        result.incoterm is not None,
        result.mode is not None,
        result.weight_kg is not None or result.volume_cbm is not None,
    ])
    result.confidence = extracted / 3.0

    return result
