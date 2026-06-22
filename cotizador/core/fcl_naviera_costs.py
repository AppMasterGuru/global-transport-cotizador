"""
FCL local costs keyed by naviera/almacén — Abel Parte 2 (2026-06-19).

Export VB + Gate Out: Abel June 22 confirmed the full 7-naviera mapping
from the EXPORTACION-CALLAO sheet of EXPO_IMPO.xlsx (Client Data/Part 2_Abel/).
Previous build only attributed 2 of 7 navieras (MAERSK via "MSK" token,
CMA CGM via "CMA" token in desglose text). The remaining 5 blocks had no
text identifier — Abel confirmed the mapping in full, enabling the
naviera-keyed table below.

  - VB amounts stored as NET pre-IGV (PDF layer applies 18% IGV at render).
    Exception: MAERSK uses RETENCIÓN 30%, not IGV — see TODO(abel-F1F4).
  - Gate Out stored per naviera (IMUPESA appears at two different amounts:
    $150 net for CMA CGM, $133.50 net for EVERGREEN).

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


# ── Real export naviera data (Session G, 2026-06-22) ────────────────────────
# Abel confirmed the full 7-naviera mapping from EXPORTACION-CALLAO sheet of
# EXPO_IMPO.xlsx (Client Data/Part 2_Abel/). Previous build only attributed
# MAERSK and CMA CGM via desglose text tokens; the other 5 navieras had no
# text identifier and were left unattributed (ABEL_FOLLOWUPS.md, now closed).
#
# vb_net_usd: NET pre-IGV. PDF layer adds 18% IGV at render (IGV-once rule).
#   Exception — MAERSK: uses RETENCIÓN 30%, not IGV. Base monto=$112,
#   retención=$48, total=$160. Stored as $160 until retención handling is
#   implemented. TODO(abel-F1F4): validate MAERSK retención treatment.
#
# gate_out: keyed by depot name per naviera. Gate out is not wired into
#   routes.py yet — available for future use. IMUPESA carries a different
#   amount per naviera ($150 for CMA CGM, $133.50 for EVERGREEN); the old
#   almacén-keyed table could not represent this — the naviera-keyed
#   structure resolves it correctly.
_EXPORT_VB_BY_NAVIERA: dict[str, dict] = {
    "MSC": {
        "vb_net_usd": 365.0,
        "gate_out": {
            "MEDLOG": {"net": 152.0, "igv": 27.36, "total": 179.36},
        },
    },
    "ONE": {
        "vb_net_usd": 272.0,
        "gate_out": {
            "CONTRANS": {"net": 150.0, "igv": 27.0, "total": 177.0},
            "DPW":      {"net": 150.0, "igv": 27.0, "total": 177.0},
        },
    },
    "MAERSK": {  # TODO(abel-F1F4): retención 30%, not IGV. Base=$112, total=$160.
        "vb_net_usd": 160.0,
        "gate_out": {
            "DEMARES": {"net": 179.0, "igv": 32.22, "total": 211.22},
        },
    },
    "HAPAG LLOYD": {
        "vb_net_usd": 152.0,
        "gate_out": {
            "RANSA": {"net": 150.0, "igv": 27.0, "total": 177.0},
        },
    },
    "CMA CGM": {
        "vb_net_usd": 219.35,
        "gate_out": {
            "IMUPESA": {"net": 150.0, "igv": 27.0, "total": 177.0},
        },
    },
    "COSCO": {
        "vb_net_usd": 100.0,
        "gate_out": {
            "FARGOLINE": {"net": 125.5, "igv": 22.59, "total": 148.09},
        },
    },
    "EVERGREEN": {
        "vb_net_usd": 227.0,
        "gate_out": {
            "TPP":                {"net": 120.5, "igv": 21.69, "total": 142.19},
            "IMUPESA":            {"net": 133.5, "igv": 24.03, "total": 157.53},
            "DP WORLD LOGISTICS": {"net": 120.5, "igv": 21.69, "total": 142.19},
        },
    },
}


def _export_vb_lookup(naviera: str) -> dict | None:
    """Look up _EXPORT_VB_BY_NAVIERA by naviera name. Handles 'X / Y' form names."""
    key = naviera.strip().upper()
    entry = _EXPORT_VB_BY_NAVIERA.get(key)
    if entry is None and "/" in key:
        entry = _EXPORT_VB_BY_NAVIERA.get(key.split("/")[0].strip())
    return entry


def get_export_vb_net_usd(naviera: str) -> float | None:
    """Net pre-IGV export VB cost by naviera (PDF layer adds 18% IGV). None if unknown."""
    entry = _export_vb_lookup(naviera)
    return entry["vb_net_usd"] if entry else None


def get_export_gate_outs(naviera: str) -> dict[str, dict]:
    """Gate Out almacenes for a naviera, keyed by depot name. Empty dict if unknown."""
    entry = _export_vb_lookup(naviera)
    return entry.get("gate_out", {}) if entry else {}
