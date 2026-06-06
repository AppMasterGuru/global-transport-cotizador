"""
Unit detection and conversion for cargo dimensions and weight.

Abel does these calculations manually on a separate calculator today.
The cotizador must detect units and convert automatically.

Supported:
  Weight : kg, lbs
  Length : cm, m, inches
  Volume : CBM computed from L×W×H, or entered directly
"""

from __future__ import annotations

from dataclasses import dataclass

IGV_RATE = 0.18  # Peru VAT


# ── Weight ──────────────────────────────────────────────────────────────────

def lbs_to_kg(lbs: float) -> float:
    return lbs * 0.453592


def kg_to_lbs(kg: float) -> float:
    return kg * 2.20462


def parse_weight(value: float, unit: str) -> float:
    """Return weight in kg regardless of input unit."""
    u = unit.lower().strip()
    if u in ("kg", "kgs", "kilogram", "kilograms"):
        return value
    if u in ("lb", "lbs", "pound", "pounds"):
        return lbs_to_kg(value)
    raise ValueError(f"Unknown weight unit: {unit!r}")


# ── Length ──────────────────────────────────────────────────────────────────

def inches_to_cm(inches: float) -> float:
    return inches * 2.54


def m_to_cm(m: float) -> float:
    return m * 100.0


def cm_to_m(cm: float) -> float:
    return cm / 100.0


def parse_length(value: float, unit: str) -> float:
    """Return length in cm regardless of input unit."""
    u = unit.lower().strip()
    if u in ("cm", "cms", "centimeter", "centimeters", "centimetre", "centimetres"):
        return value
    if u in ("m", "meter", "meters", "metre", "metres"):
        return m_to_cm(value)
    if u in ("in", "inch", "inches"):
        return inches_to_cm(value)
    raise ValueError(f"Unknown length unit: {unit!r}")


# ── Volume ───────────────────────────────────────────────────────────────────

def cbm_from_cm(
    length_cm: float,
    width_cm: float,
    height_cm: float,
    qty: int = 1,
) -> float:
    """CBM = (L × W × H × qty) / 1,000,000  (all dims in cm)."""
    return (length_cm * width_cm * height_cm * qty) / 1_000_000


def cbm_from_inches(
    length_in: float,
    width_in: float,
    height_in: float,
    qty: int = 1,
) -> float:
    return cbm_from_cm(
        inches_to_cm(length_in),
        inches_to_cm(width_in),
        inches_to_cm(height_in),
        qty,
    )


def cbm_from_m(
    length_m: float,
    width_m: float,
    height_m: float,
    qty: int = 1,
) -> float:
    return cbm_from_cm(
        m_to_cm(length_m),
        m_to_cm(width_m),
        m_to_cm(height_m),
        qty,
    )


# ── IGV ─────────────────────────────────────────────────────────────────────

def add_igv(amount: float) -> float:
    """Apply 18% Peru IGV to an amount."""
    return round(amount * (1 + IGV_RATE), 4)


def strip_igv(amount_with_igv: float) -> float:
    """Remove IGV from a gross amount."""
    return round(amount_with_igv / (1 + IGV_RATE), 4)


# ── Cargo dataclass (convenience) ────────────────────────────────────────────

@dataclass
class CargoMeasurements:
    weight_kg: float
    length_cm: float
    width_cm: float
    height_cm: float
    quantity: int = 1

    @property
    def volume_cbm(self) -> float:
        return cbm_from_cm(self.length_cm, self.width_cm, self.height_cm, self.quantity)
