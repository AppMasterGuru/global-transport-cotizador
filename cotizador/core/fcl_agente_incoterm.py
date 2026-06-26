"""
Per-incoterm concept registry for the FCL Agente Internacional path.

Source: TARIFARIO AGENTES EXPO GT - 2025 - V2 (5).xlsx (sheets "FCL EXW EXPO"
and "FCL FOB EXPO ") and TARIFARIO AGENTES IMPO GT - 2025 - V2 (4).xlsx
(sheets "FCL DAP IMPO" and "FCL DDP IMPO"), venta (right-hand) column only.
Abel confirmed 2026-06-26 that these sheets are authoritative and complete.

Registry key: (flujo, incoterm) where flujo ∈ {"EXPO","IMPO"}.
Four confirmed incoterms: EXPO EXW, EXPO FOB, IMPO DAP.

IMPO DDP — NOT in this registry. STOP condition triggered (Section 5):
  The DDP tariff sheet (example naviera: ONE) produces amounts that differ
  from current FCL DDP behavior in multiple ways:
    1. BL Master: sheet=USD 37 vs ONE current MBL=USD 29.50 (+IGV).
    2. SCAC: sheet=USD 60/BL vs ONE VB data=USD 42/Cntr — different unit
       AND different amount.
    3. Customs Broker: sheet=0.35% of CIF value (min USD 110) — structurally
       different from current Alefero/OEA fixed-commission structure.
    4. Operative Charge (USD 20/BL) and Gate in (USD 210/CONT) — concepts
       not present in the current FCL system.
    5. Terminal Fee: sheet=USD 245 (20STD) vs port_costs.py DPW import=USD 330;
       APM import=USD 302.10.
    6. Box Fee (USD 155/CONT) and Doc Fee (USD 115/BL) flagged LOCAL (+IGV) on
       the DDP sheet, but INTL (no IGV) in the current vb_importacion layer.
  Per the standing rule (Section 5), DDP on the agente_internacional path falls
  back to cliente_local FCL behavior. Await Abel/Barney decision before wiring.

Adding a new incoterm later: add one entry to _REGISTRY — no other code changes.
"""

from __future__ import annotations

from typing import Optional

# ── Concept unit constants ────────────────────────────────────────────────────

PER_BL         = "PER_BL"         # charged once per shipment (1 BL)
PER_CNTR       = "PER_CNTR"       # charged per container
PER_CNTR_EXTRA = "PER_CNTR_EXTRA" # per extra container (num_containers - 1); omitted if 0
BY_SIZE        = "BY_SIZE"        # amount varies by container type (use amount_by_size)
DYNAMIC        = "DYNAMIC"        # amount supplied at runtime (Open Transport pickup/delivery)


# ── Concept definition ────────────────────────────────────────────────────────

class FclConcept:
    """Immutable concept entry in the per-incoterm registry."""

    __slots__ = (
        "description", "unit", "igv_applicable", "is_international",
        "amount_usd", "amount_by_size", "is_collect",
    )

    def __init__(
        self,
        description: str,
        unit: str,
        *,
        igv_applicable: bool,
        is_international: bool,
        amount_usd: Optional[float] = None,
        amount_by_size: Optional[dict] = None,
        is_collect: bool = False,
    ) -> None:
        self.description      = description
        self.unit             = unit
        self.igv_applicable   = igv_applicable
        self.is_international = is_international
        self.amount_usd       = amount_usd
        self.amount_by_size   = amount_by_size
        self.is_collect       = is_collect

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FclConcept({self.description!r}, unit={self.unit!r}, "
            f"amount_usd={self.amount_usd!r})"
        )


# ── Per-incoterm registry ─────────────────────────────────────────────────────
# Amounts are pre-IGV venta values transcribed from the TARIFARIO sheets.
# IGV (18%) is applied at render time by the PDF layer.

_REGISTRY: dict[tuple[str, str], tuple[FclConcept, ...]] = {

    # ── EXPO EXW ─────────────────────────────────────────────────────────────
    # Source: "FCL EXW EXPO" sheet venta column (TARIFA NETA).
    # Ocean Freight is COLLECT — shown as 0 for transparency.
    ("EXPO", "EXW"): (
        FclConcept(
            "Flete Internacional (COLLECT)", PER_CNTR,
            igv_applicable=False, is_international=True,
            amount_usd=0.0, is_collect=True,
        ),
        FclConcept(
            "Customs Broker", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=50.0,
        ),
        FclConcept(
            "Customs Broker — Contenedor Adicional", PER_CNTR_EXTRA,
            igv_applicable=True, is_international=False,
            amount_usd=25.0,
        ),
        FclConcept(
            "Operative Charge", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=20.0,
        ),
        FclConcept(
            "Seal", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=10.0,
        ),
        FclConcept(
            "Coordinación y Supervisión del Embarque", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=214.0,
        ),
        FclConcept(
            "Agency Fee", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=5.35,
        ),
        FclConcept(
            "Gate out", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=150.0,
        ),
        FclConcept(
            "Terminal Fee", BY_SIZE,
            igv_applicable=True, is_international=False,
            amount_by_size={"20STD": 212.0, "40STD": 311.0, "40HC": 338.0},
        ),
        # Pick up: amount supplied at runtime from Open Transport district lookup
        FclConcept(
            "Pick up", DYNAMIC,
            igv_applicable=True, is_international=False,
        ),
    ),

    # ── EXPO FOB ─────────────────────────────────────────────────────────────
    # Source: "FCL FOB EXPO " sheet, notes table rows 40-43:
    # "Los siguientes costos deben ser cobrados al exportador".
    ("EXPO", "FOB"): (
        FclConcept(
            "Handling", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=85.0,
        ),
        FclConcept(
            "Doc Fee / Por BL", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=25.0,
        ),
    ),

    # ── IMPO DAP ─────────────────────────────────────────────────────────────
    # Source: "FCL DAP IMPO" sheet venta column (TARIFA NETA).
    # THC and ISPS: IGV-exempt (international carrier charges) — consistent
    # with F3 fix (Session I) and DAP sheet IGV column (empty for these rows).
    ("IMPO", "DAP"): (
        FclConcept(
            "THC", PER_CNTR,
            igv_applicable=False, is_international=True,
            amount_usd=60.0,
        ),
        FclConcept(
            "ISPS", PER_CNTR,
            igv_applicable=False, is_international=True,
            amount_usd=39.0,
        ),
        FclConcept(
            "BL Master", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=55.0,
        ),
        FclConcept(
            "Coordinación y Supervisión del Embarque", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=190.0,
        ),
        FclConcept(
            "Agency Fee", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=4.75,
        ),
        FclConcept(
            "Gate in", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=205.0,
        ),
        FclConcept(
            "Terminal Fee", BY_SIZE,
            igv_applicable=True, is_international=False,
            amount_by_size={"20STD": 245.0, "40STD": 345.0, "40HC": 372.0},
        ),
        # Delivery: amount supplied at runtime from Open Transport district lookup
        FclConcept(
            "Delivery", DYNAMIC,
            igv_applicable=True, is_international=False,
        ),
    ),

    # IMPO DDP intentionally absent — see module docstring for STOP report.
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_incoterm_concepts(
    flujo: str,
    incoterm: str,
) -> Optional[tuple[FclConcept, ...]]:
    """
    Return the ordered concept tuple for (flujo, incoterm), or None if not
    registered.  Caller should fall back to cliente_local FCL behavior when
    None is returned.

    flujo:    "EXPO" | "IMPO"
    incoterm: "EXW" | "FOB" | "DAP" | ...
    """
    return _REGISTRY.get((flujo.upper(), incoterm.upper()))


def build_agente_venta_items(
    concepts: tuple[FclConcept, ...],
    num_containers: int,
    container_type: str,
    open_transport_usd: float = 0.0,
) -> list[dict]:
    """
    Build a venta line-item list from a per-incoterm concept tuple.

    Registry amounts are pre-IGV tariff values that already include GT's
    markup — no additional margin factor is applied on top.  IGV is applied
    by the PDF render layer, the same as every other item in the cotizador.

    open_transport_usd: pre-IGV USD from open_transport_delivery_usd(), or 0
        when no district is selected. DYNAMIC concepts are omitted when 0.

    container_type: "20STD" | "40STD" | "40HC"
    """
    _INTL  = {"is_international": True,  "is_local": False, "igv_applicable": False}
    _LOCAL = {"is_international": False, "is_local": True,  "igv_applicable": True}

    items: list[dict] = []

    for c in concepts:
        flags = _INTL if c.is_international else _LOCAL

        if c.unit == PER_CNTR:
            unit_price = round(c.amount_usd, 2)
            total      = round(c.amount_usd * num_containers, 2)
            quantity   = num_containers

        elif c.unit == PER_BL:
            unit_price = round(c.amount_usd, 2)
            total      = unit_price
            quantity   = 1

        elif c.unit == PER_CNTR_EXTRA:
            extra = max(0, num_containers - 1)
            if extra == 0:
                continue
            unit_price = round(c.amount_usd, 2)
            total      = round(c.amount_usd * extra, 2)
            quantity   = extra

        elif c.unit == BY_SIZE:
            base       = (c.amount_by_size or {}).get(container_type, 0.0)
            unit_price = round(base, 2)
            total      = round(base * num_containers, 2)
            quantity   = num_containers

        elif c.unit == DYNAMIC:
            if open_transport_usd <= 0:
                continue
            unit_price = round(open_transport_usd, 2)
            total      = unit_price
            quantity   = 1

        else:
            continue

        items.append({
            "description": c.description,
            "quantity":    quantity,
            "unit_price":  unit_price,
            "total":       total,
            **flags,
        })

    return items


def registered_incoterms() -> list[tuple[str, str]]:
    """Return all (flujo, incoterm) pairs currently in the registry."""
    return list(_REGISTRY.keys())
