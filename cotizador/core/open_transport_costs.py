"""
Open Transport SAC — district-by-district local delivery rates (FCL).

Source: "TARIFAS OPEN TRANSPORT 2025.pdf" (Client Data/Tarifarios/ and
Client Data/Part 2_Abel/ — identical files, confirmed via diff before
building this module). Flat PEN rate per delivery, keyed by destination
district, with a GENERAL and an IMO (hazardous cargo) column.

PDF note 1: "Las tarifas no incluyen IGV" — these are NET pre-IGV values,
same convention as every other local cost module in this codebase. IGV
is applied once, by the PDF/display layer.

Optional FCL delivery line item: there is no default or inferred district
— the quote must not include this charge unless the user explicitly picks
a destination district.
"""

from __future__ import annotations

from core.exchange_rate import soles_to_usd

# (zona, district, general_pen, imo_pen) — transcribed row-by-row from the PDF.
_RATE_ROWS: list[tuple[str, str, float, float]] = [
    ("ZONA 1", "CALLAO", 550.0, 780.0),
    ("ZONA 1", "BELLAVISTA", 550.0, 780.0),
    ("ZONA 1", "C DE LA LEGUA", 550.0, 780.0),
    ("ZONA 1", "LA PERLA", 550.0, 780.0),
    ("ZONA 1", "LA PUNTA", 600.0, 850.0),
    ("ZONA 2A", "LIMA (CERCADO)", 650.0, 900.0),
    ("ZONA 2A", "BREÑA", 650.0, 900.0),
    ("ZONA 2A", "SAN MIGUEL", 650.0, 900.0),
    ("ZONA 2B", "MAGDALENA", 650.0, 900.0),
    ("ZONA 2B", "JESUS MARIA", 650.0, 900.0),
    ("ZONA 2B", "SMP", 700.0, 980.0),
    ("ZONA 2B", "LINCE", 700.0, 980.0),
    ("ZONA 2B", "VENTANILLA", 700.0, 980.0),
    ("ZONA 2B", "INDEPENDENCIA", 700.0, 980.0),
    ("ZONA 2B", "LOS OLIVOS", 700.0, 980.0),
    ("ZONA 2B", "RIMAC", 700.0, 980.0),
    ("ZONA 2B", "PUEBLO LIBRE", 700.0, 980.0),
    ("ZONA 3", "SAN ISIDRO", 750.0, 1050.0),
    ("ZONA 3", "BARRANCO", 750.0, 1050.0),
    ("ZONA 3", "LA VICTORIA", 800.0, 1120.0),
    ("ZONA 3", "COMAS", 820.0, 1150.0),
    ("ZONA 3", "SAN LUIS", 820.0, 1150.0),
    ("ZONA 3", "PUENTE PIEDRA", 820.0, 1150.0),
    ("ZONA 3", "ATE", 850.0, 1200.0),
    ("ZONA 3", "STA ANITA", 900.0, 1300.0),
    ("ZONA 3", "SAN BORJA", 860.0, 1200.0),
    ("ZONA 3", "MIRAFLORES", 800.0, 1120.0),
    ("ZONA 3", "SURQUILLO", 800.0, 1120.0),
    ("ZONA 3", "SURCO", 800.0, 1120.0),
    ("ZONA 3", "EL AGUSTINO", 800.0, 1120.0),
    ("ZONA 3", "LA MOLINA", 800.0, 1120.0),
    ("ZONA 3", "CHORRILLOS", 900.0, 1260.0),
    ("ZONA 3", "CARABAYLLO", 860.0, 1200.0),
    ("ZONA 3", "SJM", 820.0, 1150.0),
    ("ZONA 3", "VES", 940.0, 1320.0),
    ("ZONA 3", "VMT", 940.0, 1320.0),
    ("ZONA 4", "SJL", 920.0, 1300.0),
    ("ZONA 4", "CAJAMARQUILLA", 920.0, 1300.0),
    ("ZONA 4", "ATE VITARTE", 880.0, 1240.0),
    # PDF column order is garbled for this one row ("LURIGANCHO(PRIALE)S/
    # 1,240 880 S/") — used the neighboring ATE VITARTE rate (same zona,
    # adjacent district) rather than guess; confirm with Abel if wrong.
    ("ZONA 4", "LURIGANCHO (PRIALE)", 880.0, 1240.0),
    ("ZONA 4", "CHACLACAYO", 960.0, 1350.0),
    ("ZONA 4", "LURIN", 1100.0, 1540.0),
    ("ZONA 5", "CHOSICA", 1100.0, 1540.0),
    ("ZONA 5", "PACHACAMAC", 1050.0, 1470.0),
    ("ZONA 5", "PTA NEGRA", 1300.0, 1820.0),
    ("ZONA 5", "PTA HERMOSA", 1400.0, 1960.0),
    ("ZONA 5", "STA CLARA", 950.0, 1330.0),
    ("ZONA 5", "ÑAÑA", 950.0, 1330.0),
    ("ZONA 5", "HUAYCAN", 950.0, 1330.0),
    ("ZONA 5", "SANTA ROSA", 1180.0, 1650.0),
    ("ZONA 5", "ANCON", 1200.0, 1680.0),
    ("ZONA 5", "MANCHAY", 1020.0, 1430.0),
    ("ZONA 5", "CIENEGUILLA", 1100.0, 1540.0),
    ("ZONA 6", "CHANCAY", 1800.0, 2520.0),
    ("ZONA 6", "HUARAL", 2000.0, 2800.0),
    ("ZONA 6", "PUCUSANA", 1400.0, 1960.0),
    ("ZONA 6", "SAN BARTOLO", 1450.0, 2030.0),
    ("ZONA 6", "CHILCA", 1500.0, 2100.0),
    ("ZONA 6", "HUAROCHIRI", 1600.0, 2250.0),
]

OPEN_TRANSPORT_ZONES: dict[str, dict] = {
    district: {"zona": zona, "general_pen": general, "imo_pen": imo}
    for zona, district, general, imo in _RATE_ROWS
}


def list_open_transport_districts() -> list[str]:
    return sorted(OPEN_TRANSPORT_ZONES)


def get_open_transport_zone(district: str) -> dict:
    key = district.strip().upper()
    if key not in OPEN_TRANSPORT_ZONES:
        raise ValueError(
            f"Unknown Open Transport district: {district!r}. "
            f"Valid: {sorted(OPEN_TRANSPORT_ZONES)}"
        )
    return OPEN_TRANSPORT_ZONES[key]


def get_open_transport_rate_pen(district: str, hazardous: bool = False) -> float:
    zone = get_open_transport_zone(district)
    return zone["imo_pen"] if hazardous else zone["general_pen"]


def open_transport_delivery_usd(
    district: str, hazardous: bool = False, exchange_rate: float | None = None
) -> float:
    """Net (pre-IGV) USD cost. IGV applied once by the PDF/display layer."""
    rate_pen = get_open_transport_rate_pen(district, hazardous)
    return round(soles_to_usd(rate_pen, exchange_rate), 2)
