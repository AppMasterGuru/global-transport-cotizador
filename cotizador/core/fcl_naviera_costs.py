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
