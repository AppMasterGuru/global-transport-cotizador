"""
Per-incoterm concept registry for the FCL Agente Internacional path.

Source: TARIFARIO AGENTES EXPO/IMPO GT - 2025 sheets define WHICH concepts
appear per incoterm. Abel confirmed 2026-06-26 these sheets are authoritative
for structure.

Registry key: (flujo, incoterm) where flujo ∈ {"EXPO","IMPO"}.
Four wired incoterms: EXPO EXW, EXPO FOB, IMPO DAP, IMPO DDP.

Session L (Abel's reframe): the tariff sheet defines WHICH concepts appear,
not the amounts. Naviera/port-dependent concepts carry the RESOLVED unit and
get their amount injected at runtime from the same doc sources the
cliente_local import path already uses — so the agente amounts MATCH the
validated cliente_local figures:
  - Terminal Fee  ← port_costs.get_port_cost() (merged port + depósito)
  - THC / ISPS    ← fcl_import_costs (naviera import)
  - BL Master / Emisión MBL ← fcl_import_costs MBL
  - Visto Bueno (Importación) ← fcl_import_costs VB importación
  - Customs Broker (DDP) ← fcl_customs_broker (% of CIF + floor)
GT's own fixed service fees keep their fixed values (Operative Charge, Agency
Fee, Coordinación, Seal, the export Customs Broker base).

Two concepts have NO clean doc source — left at their sheet value and flagged
(Session L STOP, do not guess a sheet→doc equivalence):
  - EXW "Gate out": export gate is per-depot and multi-valued
    (fcl_naviera_costs.get_export_gate_outs returns a dict, not one figure)
    and is not wired into any cost var. Kept at USD 150.
  - DAP "Gate in": no import-gate doc source exists in the system. Kept at
    USD 205. (DDP's COST-only Gate in USD 210 is a separate new §2 value.)

DDP (§2/§3/§4): THC/ISPS/MBL/VB-import/Terminal resolved from the existing
import figures; Operative Charge USD 20/BL (venta); calculated Customs Broker;
Delivery (Open Transport). Gate in USD 210/CONT is COST-only (added in
routes.py costeo) and never a venta concept. The VB importación bundle already
includes box fee / SCAC / doc fee / coordinación per naviera, so DDP does not
itemize those again (no double-count).

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
RESOLVED       = "RESOLVED"       # amount injected at runtime from a doc source
                                  # (port_costs / naviera figures), keyed by description


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
# Fixed amounts are pre-IGV venta values (GT's own service fees). RESOLVED
# amounts are injected at runtime from doc sources. IGV (18%) is applied at
# render time by the PDF layer.

_REGISTRY: dict[tuple[str, str], tuple[FclConcept, ...]] = {

    # ── EXPO EXW ─────────────────────────────────────────────────────────────
    # Ocean Freight is COLLECT — shown as 0 for transparency.
    # Terminal Fee re-sourced (Session L) from port_costs export; Gate out kept
    # fixed (no clean doc source — STOP-listed).
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
        # Gate out: NO clean doc source (export gate is per-depot/multi-valued,
        # not wired). STOP-listed — kept at sheet value, do not re-source.
        FclConcept(
            "Gate out", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=150.0,
        ),
        # Terminal Fee: re-sourced from port_costs (export). Single merged
        # port+depósito line (preserves F4). Amount injected at runtime.
        FclConcept(
            "Terminal Fee", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        # Pick up: amount supplied at runtime from Open Transport district lookup
        FclConcept(
            "Pick up", DYNAMIC,
            igv_applicable=True, is_international=False,
        ),
    ),

    # ── EXPO FOB ─────────────────────────────────────────────────────────────
    # Ocean Freight ONLY (Abel F3/F4 2026-07-06). The FCL FOB EXPO TARIFA NETA
    # (client-facing right-hand block of the tab) lists a single client concept:
    # Ocean Freight (COLLECT, by container size, 0.00). The Handling 85 / Doc
    # Fee 25 that Session J (e20d521) put here come from a SEPARATE lower table
    # on the same tab headed "Los siguientes costos deben ser cobrados al
    # exportador" — origin costs billed directly to the exporter, NOT part of
    # the FOB net tariff. Under FOB the consignee/agent arranges main carriage
    # collect, so the only client-facing line is the collect ocean freight.
    # Concept emission only; USD 0.00 is a valid render (keeps the proforma
    # "Costos de Flete Internacional" section present).
    ("EXPO", "FOB"): (
        FclConcept(
            "Flete Internacional (COLLECT)", PER_CNTR,
            igv_applicable=False, is_international=True,
            amount_usd=0.0, is_collect=True,
        ),
    ),

    # ── IMPO DAP ─────────────────────────────────────────────────────────────
    # THC/ISPS/BL Master/Terminal re-sourced (Session L) from the naviera import
    # docs; Coordinación/Agency kept fixed (GT fees); Gate in kept fixed (no
    # clean doc source — STOP-listed). THC/ISPS stay IGV-exempt (international).
    ("IMPO", "DAP"): (
        FclConcept(
            "THC", RESOLVED,
            igv_applicable=False, is_international=True,
        ),
        FclConcept(
            "ISPS", RESOLVED,
            igv_applicable=False, is_international=True,
        ),
        FclConcept(
            "BL Master", RESOLVED,
            igv_applicable=True, is_international=False,
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
        # Gate in: NO clean import-gate doc source. STOP-listed — kept fixed.
        FclConcept(
            "Gate in", PER_CNTR,
            igv_applicable=True, is_international=False,
            amount_usd=205.0,
        ),
        # Terminal Fee: re-sourced from port_costs (import).
        FclConcept(
            "Terminal Fee", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        # Delivery: amount supplied at runtime from Open Transport district lookup
        FclConcept(
            "Delivery", DYNAMIC,
            igv_applicable=True, is_international=False,
        ),
    ),

    # ── IMPO DDP ─────────────────────────────────────────────────────────────
    # Session L §2/§3/§4. Keeps the system's existing naviera/port figures
    # (THC/ISPS/MBL/VB-import/Terminal, all RESOLVED), plus the §2 additions
    # (Operative Charge venta; Gate in is COST-only in routes.py) and the §3
    # calculated Customs Broker. §4: MBL + VB importación afecto IGV; THC/ISPS
    # exempt. No separate Coordinación/Agency lines — they are inside the VB
    # importación bundle (no double-count).
    ("IMPO", "DDP"): (
        FclConcept(
            "THC", RESOLVED,
            igv_applicable=False, is_international=True,
        ),
        FclConcept(
            "ISPS", RESOLVED,
            igv_applicable=False, is_international=True,
        ),
        FclConcept(
            "Emisión MBL", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        FclConcept(
            "Visto Bueno (Importación)", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        FclConcept(
            "Terminal Fee", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        FclConcept(
            "Operative Charge", PER_BL,
            igv_applicable=True, is_international=False,
            amount_usd=20.0,
        ),
        FclConcept(
            "Customs Broker", RESOLVED,
            igv_applicable=True, is_international=False,
        ),
        FclConcept(
            "Delivery", DYNAMIC,
            igv_applicable=True, is_international=False,
        ),
    ),
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
    incoterm: "EXW" | "FOB" | "DAP" | "DDP" | ...
    """
    return _REGISTRY.get((flujo.upper(), incoterm.upper()))


def build_agente_venta_items(
    concepts: tuple[FclConcept, ...],
    num_containers: int,
    container_type: str,
    open_transport_usd: float = 0.0,
    resolved_amounts: Optional[dict] = None,
) -> list[dict]:
    """
    Build a venta line-item list from a per-incoterm concept tuple.

    Fixed registry amounts are pre-IGV tariff values that already include GT's
    markup — no additional margin factor is applied on top.  IGV is applied by
    the PDF render layer, the same as every other item in the cotizador.

    open_transport_usd: pre-IGV USD from open_transport_delivery_usd(), or 0
        when no district is selected. DYNAMIC concepts are omitted when 0.

    resolved_amounts: optional {description: pre-IGV USD} mapping supplying the
        amount for RESOLVED concepts (naviera/port-dependent figures sourced
        from the same docs the cliente_local import path uses). A RESOLVED
        concept whose amount is missing or <= 0 is omitted — no silent default.

    container_type: "20STD" | "40STD" | "40HC"
    """
    _INTL  = {"is_international": True,  "is_local": False, "igv_applicable": False}
    _LOCAL = {"is_international": False, "is_local": True,  "igv_applicable": True}
    resolved = resolved_amounts or {}

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

        elif c.unit == RESOLVED:
            amt = resolved.get(c.description)
            if amt is None or amt <= 0:
                continue  # doc figure unavailable — omit, never default
            unit_price = round(amt, 2)
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


# ── Per-incoterm form-field visibility ────────────────────────────────────────
# The New Quote form gates each OPTIONAL agente FCL input on whether the concept
# it feeds is present in the selected incoterm's registry set. Deriving the map
# from _REGISTRY keeps the form and the costeo in lock-step: adding/removing a
# concept automatically shows/hides its input. Structural inputs (Flete
# Internacional, Tipo/N° Contenedor, Margen, the client-type selector) are not
# gated — they apply to every FCL agente quote.

# Concepts whose amount is resolved from the selected naviera's import docs; the
# Naviera selector is only meaningful when one of these is in the structure.
_NAVIERA_SOURCED = frozenset({
    "THC", "ISPS", "BL Master", "Emisión MBL", "Visto Bueno (Importación)",
})


def agente_field_visibility(flujo: str, incoterm: str) -> Optional[dict]:
    """
    Which optional New-Quote FCL inputs apply to (flujo, incoterm) on the
    agente_internacional path, derived from the concept registry. Returns None
    for an unregistered pair (agente then falls back to cliente_local, so the
    form imposes no per-incoterm restriction).

    Keys (all bool):
      naviera     Naviera (FCL)                    ← naviera-sourced RESOLVED
      terminal    Terminal Portuario (FCL)         ← Terminal Fee
      thc         THC Tarifa + THC Mínimo          ← THC / ISPS
      transporte  Transporte Local (district + IMO)← DYNAMIC (Pick up/Delivery)
      oea         Cliente requiere agente OEA+BASC ← Customs Broker
      ddp_cif     Valor Factura + Seguro           ← DDP CIF (DDP only)
    """
    concepts = get_incoterm_concepts(flujo, incoterm)
    if concepts is None:
        return None
    descs = {c.description for c in concepts}
    return {
        "naviera":    bool(descs & _NAVIERA_SOURCED),
        "terminal":   "Terminal Fee" in descs,
        "thc":        bool(descs & {"THC", "ISPS"}),
        "transporte": any(c.unit == DYNAMIC for c in concepts),
        "oea":        "Customs Broker" in descs,
        "ddp_cif":    incoterm.upper() == "DDP",
    }


def agente_field_visibility_map() -> dict[str, dict]:
    """
    Field-visibility for every registered incoterm, keyed "FLUJO/INCOTERM"
    (e.g. "EXPO/FOB"). Injected into new_quote.html so the form-JS gating stays
    in lock-step with _REGISTRY.
    """
    return {
        f"{flujo}/{inc}": agente_field_visibility(flujo, inc)
        for flujo, inc in _REGISTRY
    }
