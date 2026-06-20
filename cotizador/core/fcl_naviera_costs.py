"""
FCL local costs keyed by naviera/almacén — Abel Parte 2 (2026-06-19).

Export side: parsed from the EXPORTACION-CALLAO sheet of EXPO_IMPO.xlsx
(Client Data/Part 2_Abel/). Two independent things live on that sheet,
identified by row shape rather than a fixed column layout (the sheet uses
merged cells, so real rows carry a lot of None padding):

  - GATE OUT: cleanly keyed by an explicit almacén/depot name in every
    block (MEDLOG, CONTRANS, DPW, DEMARES, ...). Always reliable.
  - VISTO BUENO (+ desglose): only some blocks name an identifiable
    naviera in their desglose concepts (e.g. "BOX FEE - EXPO MSK" ->
    Maersk). Blocks with no identifiable naviera token are parsed but not
    naviera-attributed — looking one up by name returns None rather than
    guessing.

Also implements the precinto recargo rule: when an export has more than
one container, the 2nd container carries a +50% surcharge of the customs
agent's commission (Abel: "si son más de 1 contendor se aplica un recargo
del 50% del costo de la comisión del agente de aduanas al segundo
contendor").
"""

from __future__ import annotations

# Desglose concept substrings -> canonical naviera name. Only blocks whose
# desglose mentions one of these tokens get naviera-attributed.
_NAVIERA_TOKENS: dict[str, str] = {
    "MSK": "MAERSK",
    "MAERSK": "MAERSK",
    "CMA": "CMA CGM",
    "MSC": "MSC",
    "COSCO": "COSCO",
}


def _compact(row: tuple) -> tuple:
    """Strip None cells — real rows pad with None from merged columns;
    every meaningful value in a row is non-None and in left-to-right order."""
    return tuple(v for v in row if v is not None)


def parse_export_naviera_sheet(ws) -> dict:
    """
    Parse the EXPORTACION-CALLAO sheet into:
      {"gate_out": {almacen_name: {net, igv, total}},
       "visto_bueno": {naviera_name: {total, desglose: [{concept, monto, igv_or_retencion, total, tipo}]}}}
    """
    gate_out: dict[str, dict] = {}
    visto_bueno: dict[str, dict] = {}

    pending_total: float | None = None
    pending_desglose: list[dict] = []
    pending_naviera: str | None = None

    def _flush_vb_block():
        nonlocal pending_total, pending_desglose, pending_naviera
        if pending_naviera and pending_total is not None:
            visto_bueno[pending_naviera] = {
                "total": pending_total,
                "desglose": pending_desglose,
            }
        pending_total = None
        pending_desglose = []
        pending_naviera = None

    for row in ws.iter_rows(values_only=True):
        c = _compact(row)
        if not c:
            continue

        first = str(c[0]).strip() if c else ""

        # VISTO BUENO header row: ('VISTO BUENO (...)', monto, igv_or_ret, total)
        if first.upper().startswith("VISTO BUENO") and len(c) == 4:
            _flush_vb_block()
            pending_total = float(c[3])
            continue

        # GATE OUT/GATE IN row: (almacen_name, concept, net, igv, total, tipo?)
        if len(c) >= 5 and isinstance(c[1], str) and ("GATE OUT" in c[1].upper() or "GATE IN" in c[1].upper()):
            _flush_vb_block()
            name = str(c[0]).strip().upper()
            gate_out[name] = {
                "net": float(c[2]),
                "igv": float(c[3]),
                "total": float(c[4]),
            }
            continue

        # Desglose line: (concept, monto, igv_or_ret, total, tipo) — all
        # within an active VB block (pending_total is not None).
        if pending_total is not None and len(c) == 5 and isinstance(c[1], (int, float)):
            concept = str(c[0]).strip()
            entry = {
                "concept": concept,
                "monto": float(c[1]),
                "igv_or_retencion": float(c[2]),
                "total": float(c[3]),
                "tipo": str(c[4]),
            }
            pending_desglose.append(entry)
            concept_u = concept.upper()
            for token, canonical in _NAVIERA_TOKENS.items():
                if token in concept_u:
                    pending_naviera = canonical
                    break
            continue

    _flush_vb_block()
    return {"gate_out": gate_out, "visto_bueno": visto_bueno}


def get_export_gate_out(parsed: dict, name: str) -> dict | None:
    return parsed["gate_out"].get(name.strip().upper())


def get_export_visto_bueno(parsed: dict, naviera: str) -> dict | None:
    return parsed["visto_bueno"].get(naviera.strip().upper())


def second_container_surcharge(agent_commission_usd: float, container_index: int) -> float:
    """
    Precinto recargo (Abel, 2026-06-19): the 2nd container carries a +50%
    surcharge of the customs agent's commission. container_index is 1-based.
    """
    if container_index >= 2:
        return round(agent_commission_usd * 0.5, 2)
    return 0.0


def apply_second_container_surcharges(agent_commission_usd: float, num_containers: int) -> list[float]:
    """Per-container surcharge list (1-based index), first container = 0.0."""
    return [second_container_surcharge(agent_commission_usd, i) for i in range(1, num_containers + 1)]


# ── Precinto (Abel Parte 2 Q8, 2026-06-19) ──────────────────────────────────
# Alefero standard: USD 10.00 + IGV per container, flat ("por contenedor").
# Unlike the customs agent commission, precinto does NOT carry the
# 2nd-container +50% surcharge — it is the same per-container amount
# regardless of container count.
ALEFERO_PRECINTO_USD = 10.0


def precinto_total_usd(num_containers: int) -> float:
    return round(ALEFERO_PRECINTO_USD * num_containers, 2)


# ── FCL OEA+BASC tiered customs agent — export (Abel Parte 2 Q6) ───────────
# Unlike Alefero's flat commission + 2nd-container surcharge model, the
# OEA+BASC certified export agent prices per container on a volume tier:
#   1 container:  USD 70/cntr
#   2 containers: USD 50/cntr
#   3+ containers: USD 40/cntr
# Plus flat gastos operativos USD 20 (regardless of container count) and
# its own precinto rate, USD 5/cntr (separate from Alefero's USD 10/cntr).
FCL_OEA_BASC_GASTOS_OPERATIVOS_USD = 20.0
FCL_OEA_BASC_PRECINTO_USD = 5.0


def fcl_oea_basc_commission_per_container_usd(num_containers: int) -> float:
    if num_containers == 1:
        return 70.0
    if num_containers == 2:
        return 50.0
    return 40.0


def fcl_oea_basc_commission_total_usd(num_containers: int) -> float:
    return round(fcl_oea_basc_commission_per_container_usd(num_containers) * num_containers, 2)


def fcl_oea_basc_gastos_operativos_usd() -> float:
    return FCL_OEA_BASC_GASTOS_OPERATIVOS_USD


def fcl_oea_basc_precinto_total_usd(num_containers: int) -> float:
    return round(FCL_OEA_BASC_PRECINTO_USD * num_containers, 2)


# ── FCL-specific customs agent dispatch (Session E live wiring) ────────────
# The generic transport.get_customs_agent() path (flat USD 50 Alefero / USD
# 80 OEA+BASC commission, no container-count awareness) does NOT apply to
# FCL — FCL has its own rules confirmed by Abel (Q6, Q8, and the 2nd-
# container surcharge from the original Parte 2 build): Alefero charges a
# flat base commission plus the 2nd-container-onward +50% surcharge;
# OEA+BASC charges a tiered per-container commission plus flat gastos
# operativos plus its own (lower) precinto rate. This dispatch supersedes
# the generic agent for mode="fcl" only.
ALEFERO_FCL_COMMISSION_USD = 50.0  # mirrors transport.CUSTOMS_AGENTS["ALEFERO"]["commission_usd"]


def fcl_customs_agent_costs(requires_oea_basc: bool, num_containers: int) -> dict:
    """Commission + gastos operativos + precinto for the selected FCL
    customs agent, by container count. See module note above for why this
    is separate from the generic transport.get_customs_agent() path."""
    if requires_oea_basc:
        return {
            "agent_name": "OEA+BASC Certified Agent",
            "commission_usd": fcl_oea_basc_commission_total_usd(num_containers),
            "gastos_operativos_usd": fcl_oea_basc_gastos_operativos_usd(),
            "precinto_usd": fcl_oea_basc_precinto_total_usd(num_containers),
        }
    commission_total = ALEFERO_FCL_COMMISSION_USD + sum(
        apply_second_container_surcharges(ALEFERO_FCL_COMMISSION_USD, num_containers)
    )
    return {
        "agent_name": "Alefero",
        "commission_usd": round(commission_total, 2),
        "gastos_operativos_usd": 0.0,
        "precinto_usd": precinto_total_usd(num_containers),
    }


# ── Real export naviera data (Session E) ────────────────────────────────────
# Transcribed from EXPORTACION-CALLAO sheet of EXPO_IMPO.xlsx (Client
# Data/Part 2_Abel/) via parse_export_naviera_sheet(), audited 2026-06-20.
# Source file is local-only (not committed to git, not present on Railway) —
# hardcoded here, same pattern as CONSOLIDATORS/CUSTOMS_AGENTS in
# transport.py and the Open Transport district table.
#
# Of 9 VISTO BUENO blocks on the real sheet, only 2 carry an identifiable
# naviera token in their desglose text (MAERSK via "MSK", CMA CGM via
# "CMA") — same no-guessing rule as the import side before it was resolved
# (ABEL_FOLLOWUPS.md, closed item). No equivalent clean per-naviera export
# VB source has surfaced yet — see ABEL_FOLLOWUPS.md for the open follow-up.
EXPORT_NAVIERA_DATA: dict = {
    "gate_out": {
        "CONTRANS":           {"net": 150.0, "igv": 27.0,                "total": 177.0},
        "DEMARES":            {"net": 179.0, "igv": 32.22,               "total": 211.22},
        "DP WORLD LOGISTICS": {"net": 120.5, "igv": 21.689999999999998,  "total": 142.19},
        "DPW":                {"net": 150.0, "igv": 27.0,                "total": 177.0},
        "FARGOLINE":          {"net": 125.5, "igv": 22.59,               "total": 148.09},
        "IMUPESA":            {"net": 133.5, "igv": 24.029999999999998, "total": 157.53},
        "MEDLOG":             {"net": 152.0, "igv": 27.36,               "total": 179.36},
        "RANSA":              {"net": 150.0, "igv": 27.0,                "total": 177.0},
        "TPP":                {"net": 120.5, "igv": 21.689999999999998, "total": 142.19},
    },
    "visto_bueno": {
        "CMA CGM": {
            "total": 258.83299999999997,
            "desglose": [
                {"concept": "CMA - COORDINACIÓN Y SUPERVISIÓN DE EMBARQUE",
                 "monto": 214.0, "igv_or_retencion": 38.519999999999996,
                 "total": 252.51999999999998, "tipo": "CONTENEDOR"},
            ],
        },
        "MAERSK": {
            "total": 160.0,
            "desglose": [
                {"concept": "BOX FEE - EXPO MSK", "monto": 80.5,
                 "igv_or_retencion": 34.5, "total": 115.0, "tipo": "CONTENEDOR"},
                {"concept": "COVERAGE FEE - EXPO MSK", "monto": 31.5,
                 "igv_or_retencion": 13.5, "total": 45.0, "tipo": "CONTENEDOR"},
            ],
        },
    },
}


def get_export_naviera_data() -> dict:
    return EXPORT_NAVIERA_DATA
