"""
Local transport cost calculation.

Abel's rule: charge = max(weight_band_rate, cbm_band_rate)

From the demo (36:06 – 47:17):
  Example: 0.58 CBM, 295 kg
  → CBM puts it in 0.5–1 CBM band (S/180)
  → Weight at 295 kg exceeds 250 kg max for that band → S/200
  → Weight wins. Charge = S/200.

Costs are in soles (PEN). Converted to USD in the final quote via SBS rate.

LCL uses consolidators (MSL, Kraft, Saco, EQ) — NOT direct navieras.
Abel: "Para un LCL no cotizamos con la naviera de manera directa."
"""

from __future__ import annotations

IGV = 0.18

# ── Transport rate bands ─────────────────────────────────────────────────────
# (upper_bound, rate_soles)
# These are representative starting values; actual values come from Vania's
# rate card Excel (Tarifas folder → transportista sheet).

CBM_BANDS: list[tuple[float, float]] = [
    (0.5,   150.0),
    (1.0,   180.0),
    (2.0,   250.0),
    (3.0,   320.0),
    (5.0,   450.0),
    (10.0,  700.0),
]

WEIGHT_BANDS: list[tuple[float, float]] = [
    (100.0,   120.0),
    (250.0,   180.0),
    (500.0,   200.0),   # Abel's example: 295 kg → S/200
    (1000.0,  320.0),
    (2000.0,  500.0),
]

# ── Consolidators (LCL only) ─────────────────────────────────────────────────
# Visto bueno rates confirmed by Abel: Kraft $160, MSL $180, Saco $190 (+IGV)
# EQ rate is a placeholder until Vania's rate card arrives.

CONSOLIDATORS: dict[str, dict] = {
    "MSL":   {"name": "MSL",   "visto_bueno_usd": 180.0},
    "KRAFT": {"name": "Kraft", "visto_bueno_usd": 160.0},
    "SACO":  {"name": "Saco",  "visto_bueno_usd": 190.0},
    "EQ":    {"name": "EQ",    "visto_bueno_usd": 170.0},  # ASK VANIA: confirm rate
}

# ── Customs agents ────────────────────────────────────────────────────────────
# Abel: Alefero is default. OEA+BASC required for clients like Farmex.
# "$70 commission + gastos operativos + 18% IGV = ~$59.23 total"
# Note: after IGV on the net fees the total rounds to the figure Abel quoted.

CUSTOMS_AGENTS: dict[str, dict] = {
    "ALEFERO": {
        "name": "Alefero",
        "commission_usd": 50.0,   # net pre-IGV commission
        "gastos_usd": 0.19,       # gastos operativos (pre-IGV)
        "requires_oea_basc": False,
        "default": True,
    },
    "OEA_BASC": {
        "name": "OEA+BASC Certified Agent",
        "commission_usd": 80.0,
        "gastos_usd": 0.0,
        "requires_oea_basc": True,
        "default": False,
    },
}


def _band_rate(value: float, bands: list[tuple[float, float]]) -> float:
    """Return the rate for the band that value falls into."""
    for upper, rate in bands:
        if value <= upper:
            return rate
    # Beyond last band: extrapolate at last rate × 1.2
    return bands[-1][1] * 1.2


def get_cbm_rate(cbm: float) -> float:
    return _band_rate(cbm, CBM_BANDS)


def get_weight_rate(weight_kg: float) -> float:
    return _band_rate(weight_kg, WEIGHT_BANDS)


def calculate_transport(weight_kg: float, cbm: float) -> dict:
    """
    Return the transport charge breakdown.
    Charge = max(weight_band_rate, cbm_band_rate) — Abel's rule.
    """
    cbm_rate = get_cbm_rate(cbm)
    weight_rate = get_weight_rate(weight_kg)
    charge_soles = max(cbm_rate, weight_rate)
    basis = "weight" if weight_rate >= cbm_rate else "volume"

    return {
        "weight_kg": weight_kg,
        "cbm": cbm,
        "cbm_rate_soles": cbm_rate,
        "weight_rate_soles": weight_rate,
        "charge_soles": charge_soles,
        "basis": basis,
    }


def get_consolidator(name: str) -> dict:
    key = name.upper().strip()
    if key not in CONSOLIDATORS:
        raise ValueError(
            f"Unknown consolidator: {name!r}. Valid: {sorted(CONSOLIDATORS)}"
        )
    return CONSOLIDATORS[key]


def get_customs_agent(client_requires_oea_basc: bool = False) -> dict:
    """Select customs agent based on client requirements."""
    if client_requires_oea_basc:
        return CUSTOMS_AGENTS["OEA_BASC"]
    return CUSTOMS_AGENTS["ALEFERO"]


def visto_bueno_total_usd(consolidator: dict) -> float:
    """Visto bueno + IGV (USD)."""
    return round(consolidator["visto_bueno_usd"] * (1 + IGV), 4)


def customs_total_usd(agent: dict) -> float:
    """Customs agent: (commission + gastos) + IGV (USD)."""
    subtotal = agent["commission_usd"] + agent["gastos_usd"]
    return round(subtotal * (1 + IGV), 4)
