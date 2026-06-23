"""
FCL import local costs by naviera — Abel Parte 2 (2026-06-19).

Abel's explicit written rule: FCL import charges only THC + ISPS + MBL
emission. Parsed (not hardcoded) from
"Gastos de Importacion en Callao por Naviera.xlsx" (Client Data/Part 2_Abel/):
  - G. LOCALES sheet  -> THCD (20'/40') + an "adicional" concept (usually
    ISPS, sometimes DOC FEE) at 20'/40'.
  - EMISION MBL sheet -> free-text MBL emission cost per naviera (mixed
    USD/PEN, mixed "+ IGV" / flat / "NO COBRA" formats).

Abel Parte 2 Q3 (closed 2026-06-20): the second import structure — the
EXPO_IMPO "IMPORTACIÓN" sheet's "VB IMPORTACION" layer — STACKS with
THC+ISPS+MBL rather than replacing it. Parsed via parse_import_vb_sheet()
and summed in by get_fcl_import_local_costs() when a vb_importacion dict
is supplied. Only naviera-identifiable blocks (an explicit naviera token
in the desglose concept text, e.g. "BOX FEE - EXPO MSK") are attributed —
same no-guessing rule already applied to the export side's VISTO BUENO
blocks in fcl_naviera_costs.py. Unidentified blocks (no token, even if a
NOTA elsewhere hints at a naviera) are parsed but not attributed.
"""

from __future__ import annotations

import re

from core.exchange_rate import soles_to_usd

_MONEY_RE = re.compile(r"(USD|S/)\s*([\d.,]+)")

# Naviera-specific corrections/overrides on top of the raw sheet figures —
# Abel Parte 2 Q4 (2026-06-19): CMA CGM / APL THC and ISPS are corrected
# (65 / 39, both IGV-exempt), overriding the G. LOCALES "second THC row"
# ambiguity flagged as TODO(abel-Q4) last session.
_NAVIERA_OVERRIDES: dict[str, dict] = {
    "CMA CGM / APL": {
        "thc_20": 65.0,
        "thc_40": 65.0,
        "thc_igv_applicable": False,
        "isps_20": 39.0,
        "isps_40": 39.0,
        "isps_igv_applicable": False,
    },
}

# Inactive navieras — Abel confirmed no cargo with this carrier June 19
# (Q5). Excluded even though rows still exist in the source sheets.
_INACTIVE_NAVIERAS: set[str] = {"HAMBURG SUD / ALIANCA"}

# VB IMPORTACION desglose token -> canonical naviera key (matching the
# naviera strings used by get_fcl_import_local_costs / G. LOCALES). Same
# no-guessing approach as fcl_naviera_costs._NAVIERA_TOKENS: only blocks
# whose desglose mentions one of these tokens are naviera-attributed.
_VB_NAVIERA_TOKENS: dict[str, str] = {
    "MSK": "MAERSK / SEALAND",
    "CMA": "CMA CGM / APL",
}


def _parse_money(raw: str) -> dict:
    """
    Extract a currency + amount from a free-text cost cell, e.g.:
      "USD 55.00 + IGV"   -> USD 55.00, plus_igv=True
      "DOC FEE USD 55.00" -> USD 55.00, plus_igv=False
      "S/ 90.00 + IGV"    -> PEN 90.00, plus_igv=True
      "USD 29,50 + IGV"   -> USD 29.50 (comma decimal)
      "NO COBRA"          -> amount=None, no_cobra=True
    """
    raw_str = str(raw).strip()
    if "NO COBRA" in raw_str.upper():
        return {"raw": raw_str, "currency": None, "amount": None,
                "no_cobra": True, "plus_igv": False}

    m = _MONEY_RE.search(raw_str)
    if not m:
        return {"raw": raw_str, "currency": None, "amount": None,
                "no_cobra": False, "plus_igv": False}

    currency = "USD" if m.group(1) == "USD" else "PEN"
    amount_str = m.group(2)
    # Spanish-style "29,50" (comma decimal, no thousands dot) -> "29.50"
    if "," in amount_str and "." not in amount_str:
        amount_str = amount_str.replace(",", ".")
    else:
        amount_str = amount_str.replace(",", "")
    amount = float(amount_str)
    plus_igv = "+ IGV" in raw_str.upper() or "+IGV" in raw_str.upper()
    return {"raw": raw_str, "currency": currency, "amount": amount,
            "no_cobra": False, "plus_igv": plus_igv}


def parse_g_locales_sheet(ws) -> dict:
    """
    Parse the G. LOCALES sheet into:
      {naviera: {agente_maritimo, thc_20, thc_40, no_cobra,
                 adicional_concept, adicional_20, adicional_40}}
    Skips the two header rows and any orphan continuation row (a row with
    no naviera name — e.g. an alternate THC figure for the line above it).
    """
    out: dict[str, dict] = {}

    for row in ws.iter_rows(values_only=True):
        if not any(v is not None for v in row):
            continue
        naviera = row[0]
        if naviera is None:
            # Orphan continuation row (e.g. CMA/APL's alternate THC figures).
            # TODO(abel-Q4) CLOSED 2026-06-19: Abel confirmed CMA CGM/APL
            # THC=65 and ISPS=39, both IGV-exempt — applied as an override
            # in _NAVIERA_OVERRIDES rather than resolved here, since this
            # orphan row's own figures aren't the source of truth either.
            continue
        naviera_str = str(naviera).strip()
        if naviera_str.upper() in ("NAVIERA",):
            continue  # header row

        thc_20_raw = row[3] if len(row) > 3 else None
        thc_40_raw = row[4] if len(row) > 4 else None
        no_cobra = isinstance(thc_20_raw, str) and "NO COBRA" in thc_20_raw.upper()
        thc_20 = None if no_cobra or thc_20_raw is None else float(thc_20_raw)
        thc_40 = None if no_cobra or thc_40_raw is None else float(thc_40_raw)

        adicional_concept = row[5] if len(row) > 5 else None
        adicional_20 = row[6] if len(row) > 6 else None
        adicional_40 = row[7] if len(row) > 7 else None

        out[naviera_str] = {
            "agente_maritimo": row[1],
            "thc_20": thc_20,
            "thc_40": thc_40,
            "no_cobra": no_cobra,
            "adicional_concept": adicional_concept,
            "adicional_20": float(adicional_20) if isinstance(adicional_20, (int, float)) else adicional_20,
            "adicional_40": float(adicional_40) if isinstance(adicional_40, (int, float)) else adicional_40,
        }

    return out


def parse_mbl_sheet(ws) -> dict:
    """Parse the EMISION MBL sheet into {naviera: _parse_money(raw) | sea_waybill_telex}."""
    out: dict[str, dict] = {}
    for row in ws.iter_rows(values_only=True):
        if not any(v is not None for v in row):
            continue
        naviera = row[0]
        if naviera is None or str(naviera).strip().upper() == "NAVIERA":
            continue
        naviera_str = str(naviera).strip()
        raw_cost = row[1] if len(row) > 1 else None
        sea_waybill = row[2] if len(row) > 2 else None
        if raw_cost is None:
            continue
        entry = _parse_money(raw_cost)
        entry["sea_waybill_telex"] = sea_waybill
        out[naviera_str] = entry
    return out


def _lookup_mbl(mbl: dict, naviera: str) -> dict:
    """
    EMISION MBL sometimes splits a combined G. LOCALES key into separate
    rows (e.g. G. LOCALES has "CMA CGM / APL" as one line; EMISION MBL has
    "APL" and "CMA CGM" as two — both quote the same USD 55 + IGV). Try an
    exact match first, then each "/"-separated token.
    """
    if naviera in mbl:
        return mbl[naviera]
    for token in naviera.split("/"):
        token = token.strip()
        if token in mbl:
            return mbl[token]
    return {}


def parse_import_vb_sheet(ws) -> dict:
    """
    Parse the EXPO_IMPO "IMPORTACIÓN" sheet's VB IMPORTACION blocks into
    {naviera: {vb_importacion_usd, desglose}} — only for blocks whose
    desglose mentions a token in _VB_NAVIERA_TOKENS (Q3: no naviera
    guessing). Each block has the same row shape as the export sheet's
    VISTO BUENO blocks (fcl_naviera_costs.parse_export_naviera_sheet):
      - header: (concept, monto, igv_or_retencion, total) — 4 values
      - desglose line: (concept, monto, igv, total, tipo) — 5 values,
        monto numeric
      - terminated by the next ALMACÉN "GATE IN"/"GATE OUT" row
    """
    out: dict[str, dict] = {}

    pending_total: float | None = None
    pending_desglose: list[dict] = []
    pending_naviera: str | None = None

    def _flush():
        nonlocal pending_total, pending_desglose, pending_naviera
        if pending_naviera and pending_total is not None:
            out[pending_naviera] = {
                "vb_importacion_usd": pending_total,
                "desglose": pending_desglose,
            }
        pending_total = None
        pending_desglose = []
        pending_naviera = None

    for row in ws.iter_rows(values_only=True):
        c = tuple(v for v in row if v is not None)
        if not c:
            continue

        first = str(c[0]).strip() if c else ""

        if first.upper().startswith("VISTO BUENO") and len(c) == 4:
            _flush()
            pending_total = float(c[1])
            continue

        if len(c) >= 5 and isinstance(c[1], str) and ("GATE OUT" in c[1].upper() or "GATE IN" in c[1].upper()):
            _flush()
            continue

        if pending_total is not None and len(c) == 5 and isinstance(c[1], (int, float)):
            concept = str(c[0]).strip()
            pending_desglose.append({
                "concept": concept,
                "monto": float(c[1]),
                "igv_or_retencion": float(c[2]),
                "total": float(c[3]),
                "tipo": str(c[4]),
            })
            concept_u = concept.upper()
            for token, canonical in _VB_NAVIERA_TOKENS.items():
                if token in concept_u:
                    pending_naviera = canonical
                    break
            continue

    _flush()
    return out


def get_fcl_import_local_costs(g_locales: dict, mbl: dict, naviera: str, vb_importacion: dict | None = None) -> dict | None:
    """
    Combine THC + ISPS/adicional + MBL for one naviera — Abel's explicit
    THC+ISPS+MBL rule. Returns None if the naviera isn't found in
    G. LOCALES (the THC/ISPS source).

    vb_importacion (Q3, closed 2026-06-20): optional dict from
    parse_import_vb_sheet(). When the naviera has a naviera-identified VB
    IMPORTACION block, its net amount stacks in as vb_importacion_usd;
    otherwise vb_importacion_usd is None (no guessing).
    """
    if naviera in _INACTIVE_NAVIERAS:
        return None
    g = g_locales.get(naviera)
    if g is None:
        return None
    m = _lookup_mbl(mbl, naviera)
    override = _NAVIERA_OVERRIDES.get(naviera, {})
    vb = (vb_importacion or {}).get(naviera)
    return {
        "naviera": naviera,
        "thc_20": override.get("thc_20", g["thc_20"]),
        "thc_40": override.get("thc_40", g["thc_40"]),
        "thc_no_cobra": g["no_cobra"],
        "thc_igv_applicable": override.get("thc_igv_applicable", True),
        "isps_concept": g["adicional_concept"],
        "isps_20": override.get("isps_20", g["adicional_20"]),
        "isps_40": override.get("isps_40", g["adicional_40"]),
        "isps_igv_applicable": override.get("isps_igv_applicable", True),
        "mbl_usd": m.get("amount") if m.get("currency") == "USD" else None,
        "mbl_raw": m.get("raw"),
        "mbl_currency": m.get("currency"),
        "mbl_no_cobra": m.get("no_cobra", False),
        "vb_importacion_usd": vb["vb_importacion_usd"] if vb else None,
    }


# ── VB IMPORTACION sheet (Gastos de Importacion en Callao por Naviera.xlsx) ──
# Abel Parte 2 Q3 follow-up (closed 2026-06-20, ABEL_FOLLOWUPS.md item #2):
# this sheet — in the SAME workbook already parsed above for G. LOCALES and
# EMISION MBL — keys every Visto Bueno block explicitly by naviera name in
# column A. Unlike the EXPO_IMPO IMPORTACIÓN sheet's VISTO BUENO blocks
# (parse_import_vb_sheet, above; only 2 of 7 blocks naviera-identifiable),
# this sheet needs no naviera guessing at all — it supersedes
# parse_import_vb_sheet() as the source for vb_importacion in live wiring.
# parse_import_vb_sheet() is left in place (still tested) but is no longer
# the function routes.py calls for FCL import VB.

# Sheet header row name -> canonical naviera key used by G. LOCALES (this
# sheet writes "CMA-CGM / APL" with a hyphen; G. LOCALES uses "CMA CGM / APL").
_VB_IMPORTACION_NAME_FIXES: dict[str, str] = {
    "CMA-CGM / APL": "CMA CGM / APL",
}

# COSCO / OOCL prices Visto Bueno in container-count tiers rather than a
# flat per-container rate like every other naviera on this sheet. Only the
# tier concept matching the quote's num_containers contributes to the total;
# the other two tier rows for that naviera are excluded.
_COSCO_VB_TIERS: dict[str, tuple[int, int | None]] = {
    "VOBO 1 CNTR.": (1, 1),
    "VOBO 2 A 5 CNTR.": (2, 5),
    "VOBO 6 A MÁS CNTR.": (6, None),
}


def parse_vb_importacion_sheet(ws) -> dict:
    """
    Parse the Gastos de Importacion en Callao por Naviera.xlsx "VB
    IMPORTACION" sheet into {naviera: {"concepts": [{concept, unit, p_unit,
    currency, factura_agent}]}}.

    Columns: NAVIERA, CONCEPTO, POD, UNIT, P. UNIT, MONEDA, FACTURA. A
    naviera name in column A starts a new block; subsequent rows with a
    blank column A belong to that naviera until the next named row.

    "GATE IN"/"GATE OUT" concept rows are excluded — that is a separate
    almacén/gate charge (same category as fcl_naviera_costs' export-side
    gate_out), not Visto Bueno, and out of scope for this layer (Abel's
    explicit FCL import rule is THC + ISPS + MBL + VB only).

    Non-numeric P. UNIT cells (e.g. a percentage described in free text
    rather than a computed amount) are skipped rather than guessed.
    """
    out: dict[str, dict] = {}
    current_naviera: str | None = None
    current_concepts: list[dict] = []

    def _flush():
        nonlocal current_naviera, current_concepts
        if current_naviera:
            out[current_naviera] = {"concepts": current_concepts}
        current_naviera = None
        current_concepts = []

    for row in ws.iter_rows(values_only=True):
        if not any(v is not None for v in row):
            continue
        padded = tuple(row) + (None,) * max(0, 7 - len(row))
        naviera_cell, concept, _pod, unit, p_unit, moneda, factura_agent = padded[:7]

        if naviera_cell is not None:
            naviera_str = str(naviera_cell).strip()
            if naviera_str.upper() == "NAVIERA":
                continue  # header row
            if "MONTOS NO INCLUYEN IGV" in naviera_str.upper():
                continue  # footer note, not a naviera
            _flush()
            current_naviera = _VB_IMPORTACION_NAME_FIXES.get(naviera_str, naviera_str)

        if concept is None or current_naviera is None:
            continue
        concept_str = str(concept).strip()
        if "GATE IN" in concept_str.upper() or "GATE OUT" in concept_str.upper():
            continue
        if not isinstance(p_unit, (int, float)):
            continue  # non-numeric (free-text percentage, etc.) — skip, don't guess

        current_concepts.append({
            "concept": concept_str,
            "unit": str(unit).strip() if unit else None,
            "p_unit": float(p_unit),
            "currency": str(moneda).strip().upper() if moneda else None,
            "factura_agent": factura_agent,
        })

    _flush()
    return out


def build_vb_importacion_totals(
    parsed: dict, num_containers: int = 1, exchange_rate: float | None = None
) -> dict[str, dict]:
    """
    Reduce parse_vb_importacion_sheet() output to {naviera:
    {vb_importacion_usd}} — the flat shape get_fcl_import_local_costs()'s
    vb_importacion arg expects, so this slots in as a drop-in replacement
    for parse_import_vb_sheet()'s output without changing that function.

    "Cntr."-unit concepts scale by num_containers; "BL" and "Factura"-unit
    concepts are flat regardless of container count. PEN concepts are
    converted to USD via core.exchange_rate.soles_to_usd.

    COSCO / OOCL: only the tier concept matching num_containers contributes.

    TODO(abel-F1F4): figures here come from Abel's own Gastos de
    Importacion en Callao por Naviera.xlsx "VB IMPORTACION" sheet, not yet
    validated against a real quote — confirm via Abel's F1-F4 scenario run
    before treating these amounts as final, same validation gate as the
    rest of FCL.
    """
    totals: dict[str, dict] = {}
    for naviera, block in parsed.items():
        total = 0.0
        for c in block["concepts"]:
            tier = _COSCO_VB_TIERS.get(c["concept"].upper())
            if tier is not None:
                lo, hi = tier
                if not (num_containers >= lo and (hi is None or num_containers <= hi)):
                    continue
            amount = c["p_unit"]
            if c["currency"] == "PEN":
                amount = soles_to_usd(amount, exchange_rate)
            multiplier = num_containers if c["unit"] == "Cntr." else 1
            total += amount * multiplier
        totals[naviera] = {"vb_importacion_usd": round(total, 2)}
    return totals


# ── Real import reference data (Session E) ──────────────────────────────────
# Transcribed from Gastos de Importacion en Callao por Naviera.xlsx (Client
# Data/Part 2_Abel/) via parse_g_locales_sheet/parse_mbl_sheet/
# parse_vb_importacion_sheet, audited 2026-06-20. Source file is local-only
# (not committed to git, not present on Railway) — hardcoded here, same
# pattern as CONSOLIDATORS/EXPORT_NAVIERA_DATA.
G_LOCALES_DATA: dict = {
    "CMA CGM / APL": {"thc_20": 65.0, "thc_40": 70.0, "no_cobra": False,
                       "agente_maritimo": "IAN TAYLOR",
                       "adicional_concept": "ISPS", "adicional_20": 14.0, "adicional_40": 14.0},
    "COSCO / OOCL": {"thc_20": 55.0, "thc_40": 55.0, "no_cobra": False,
                      "agente_maritimo": "COSCO PERU",
                      "adicional_concept": "ISPS", "adicional_20": 6.0, "adicional_40": 6.0},
    "EVERGREEN": {"thc_20": 80.0, "thc_40": 80.0, "no_cobra": False,
                  "agente_maritimo": "GREENANDES",
                  "adicional_concept": "ISPS", "adicional_20": 10.0, "adicional_40": 10.0},
    "HAMBURG SUD / ALIANCA": {"thc_20": 90.0, "thc_40": 90.0, "no_cobra": False,
                              "agente_maritimo": "COLUMBUS", "adicional_concept": "ISPS",
                              "adicional_20": "USD 16.00 \nEUR 13.00",
                              "adicional_40": "USD 16.00 \nEUR 13.00"},
    "HAPAG LLOYD": {"thc_20": 75.0, "thc_40": 75.0, "no_cobra": False,
                     "agente_maritimo": "TRAMARSA",
                     "adicional_concept": "ISPS", "adicional_20": 13.0, "adicional_40": 13.0},
    "HYUNDAI": {"thc_20": 85.0, "thc_40": 85.0, "no_cobra": False,
                "agente_maritimo": "TRANSTOTAL",
                "adicional_concept": "ISPS", "adicional_20": 10.0, "adicional_40": 10.0},
    "MAERSK / SEALAND": {"thc_20": 110.0, "thc_40": 110.0, "no_cobra": False,
                         "agente_maritimo": "COLUMBUS",
                         "adicional_concept": "DOC FEE", "adicional_20": 55.0, "adicional_40": 55.0},
    "MSC": {"thc_20": 65.0, "thc_40": 65.0, "no_cobra": False,
            "agente_maritimo": "MSC PERU",
            "adicional_concept": None, "adicional_20": None, "adicional_40": None},
    "ONE": {"thc_20": 125.0, "thc_40": 125.0, "no_cobra": False,
            "agente_maritimo": "MERCATOR",
            "adicional_concept": "CVC", "adicional_20": 59.0, "adicional_40": 59.0},
    "PIL": {"thc_20": 84.0, "thc_40": 84.0, "no_cobra": False,
            "agente_maritimo": "TRANSMERIDIAN",
            "adicional_concept": "ISPS", "adicional_20": 20.0, "adicional_40": 20.0},
    "SEABOARD": {"thc_20": None, "thc_40": None, "no_cobra": True,
                 "agente_maritimo": "CITIKOLD",
                 "adicional_concept": None, "adicional_20": None, "adicional_40": None},
    "WAN HAI": {"thc_20": 90.0, "thc_40": 90.0, "no_cobra": False,
                "agente_maritimo": "TRANSTOTAL",
                "adicional_concept": "ISPS", "adicional_20": 10.0, "adicional_40": 10.0},
    "YANG MING": {"thc_20": 80.0, "thc_40": 80.0, "no_cobra": False,
                  "agente_maritimo": "TPP",
                  "adicional_concept": "ISPS", "adicional_20": 9.0, "adicional_40": 9.0},
    "ZIM": {"thc_20": 90.0, "thc_40": 90.0, "no_cobra": False,
            "agente_maritimo": "TPP",
            "adicional_concept": "ISPS", "adicional_20": 18.0, "adicional_40": 18.0},
}

MBL_DATA: dict = {
    "APL": {"amount": 55.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
            "raw": "USD 55.00 + IGV", "sea_waybill_telex": "NO"},
    "CMA CGM": {"amount": 55.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
                "raw": "USD 55.00 + IGV", "sea_waybill_telex": "SI"},
    "COSCO / OOCL": {"amount": 30.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
                      "raw": "USD 30.00 + IGV", "sea_waybill_telex": "SI"},
    "EVERGREEN": {"amount": None, "currency": None, "no_cobra": True, "plus_igv": False,
                  "raw": "NO COBRA", "sea_waybill_telex": "NO"},
    "HAMBURG SUD": {"amount": 30.93, "currency": "USD", "no_cobra": False, "plus_igv": False,
                    "raw": "DOC FEE USD 30.93", "sea_waybill_telex": "NO"},
    "HAPAG LLOYD": {"amount": 60.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
                     "raw": "USD 60.00 + IGV", "sea_waybill_telex": "NO"},
    "HYUNDAI": {"amount": 90.0, "currency": "PEN", "no_cobra": False, "plus_igv": True,
                "raw": "S/ 90.00 + IGV", "sea_waybill_telex": "NO"},
    "MAERSK / SEALAND": {"amount": 55.0, "currency": "USD", "no_cobra": False, "plus_igv": False,
                         "raw": "DOC FEE USD 55.00", "sea_waybill_telex": "SI"},
    "MSC": {"amount": 57.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
            "raw": "USD 57.00 + IGV", "sea_waybill_telex": "NO"},
    "ONE": {"amount": 29.5, "currency": "USD", "no_cobra": False, "plus_igv": True,
            "raw": "USD 29,50 + IGV", "sea_waybill_telex": "SI"},
    "PIL": {"amount": 145.0, "currency": "PEN", "no_cobra": False, "plus_igv": True,
            "raw": "S/ 145.00 + IGV", "sea_waybill_telex": "NO"},
    "SEABOARD": {"amount": 35.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
                 "raw": "USD 35.00 + IGV", "sea_waybill_telex": "NO"},
    "WAN HAI": {"amount": 115.0, "currency": "PEN", "no_cobra": False, "plus_igv": True,
                "raw": "S/ 115.00 + IGV", "sea_waybill_telex": "NO"},
    "YANG MING": {"amount": 50.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
                  "raw": "USD 50.00 + IGV", "sea_waybill_telex": "NO"},
    "ZIM": {"amount": 50.0, "currency": "USD", "no_cobra": False, "plus_igv": True,
            "raw": "USD 50.00 + IGV", "sea_waybill_telex": "-"},
}

VB_IMPORTACION_DATA: dict = {
    "CMA CGM / APL": {"concepts": [
        {"concept": "COORDINACIÓN Y SUPERVISIÓN DE DESCARGA", "currency": "USD",
         "factura_agent": "IAN TAYLOR", "p_unit": 190.0, "unit": "Cntr."},
        {"concept": "ADMINISTRACIÓN Y PROTECCIÓN DE EQUIPOS", "currency": "USD",
         "factura_agent": "IAN TAYLOR", "p_unit": 35.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS (2.5% FACTURA)", "currency": "USD",
         "factura_agent": "IAN TAYLOR", "p_unit": 0.0, "unit": "Factura"},
    ]},
    "COSCO / OOCL": {"concepts": [
        {"concept": "Servicio de Administración de Contenedores", "currency": "PEN",
         "factura_agent": "COSCO", "p_unit": 120.0, "unit": "Cntr."},
        {"concept": "VoBo 1 Cntr.", "currency": "PEN",
         "factura_agent": "COSCO", "p_unit": 540.0, "unit": "Cntr."},
        {"concept": "VoBo 2 a 5 Cntr.", "currency": "PEN",
         "factura_agent": "COSCO", "p_unit": 470.0, "unit": "Cntr."},
        {"concept": "VoBo 6 a más Cntr.", "currency": "PEN",
         "factura_agent": "COSCO", "p_unit": 390.0, "unit": "Cntr."},
    ]},
    "EVERGREEN": {"concepts": [
        # Abel 2026-06-22: EXPO_IMPO IMPORTACIÓN tab is authoritative ($230 DO + $65 BL = $295 net).
        # Gastos workbook figures ($250 DO + PEN 25 + $62 BL) were stale — discarded.
        {"concept": "DELIVERY ORDER", "currency": "USD",
         "factura_agent": "GREENANDES PERU", "p_unit": 230.0, "unit": "Cntr."},
        {"concept": "BL TRANSMISIÓN FEE", "currency": "USD",
         "factura_agent": "GREENANDES PERU", "p_unit": 65.0, "unit": "BL"},
    ]},
    "HAMBURG SUD / ALIANCA": {"concepts": [
        {"concept": "Container Control", "currency": "USD",
         "factura_agent": "COLUMBUS", "p_unit": 135.0, "unit": "Cntr."},
        {"concept": "Servicio de administración de contenedores (SAC)", "currency": "USD",
         "factura_agent": "COLUMBUS", "p_unit": 70.0, "unit": "Cntr."},
        {"concept": "Servicio Documentario", "currency": "USD",
         "factura_agent": "COLUMBUS", "p_unit": 55.0, "unit": "BL"},
    ]},
    "HAPAG LLOYD": {"concepts": [
        {"concept": "Gestión de Despacho de Contenedor Importación (GDCI)", "currency": "USD",
         "factura_agent": "TRAMARSA", "p_unit": 192.0, "unit": "Cntr."},
        {"concept": "Tramite Documentario de Importación (TDI)", "currency": "USD",
         "factura_agent": "TRAMARSA", "p_unit": 98.0, "unit": "BL"},
    ]},
    "HYUNDAI": {"concepts": [
        {"concept": "CONTROL & ADMINISTRACION DE CONTENEDORES", "currency": "PEN",
         "factura_agent": "TRANSTOTAL", "p_unit": 150.0, "unit": "Cntr."},
        {"concept": "BOX FEE", "currency": "PEN",
         "factura_agent": "TRANSTOTAL", "p_unit": 420.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS", "currency": "PEN",
         "factura_agent": "TRANSTOTAL", "p_unit": 70.0, "unit": "Factura"},
        {"concept": "DOC FEE", "currency": "PEN",
         "factura_agent": "TRANSTOTAL", "p_unit": 456.0, "unit": "BL"},
        {"concept": "GTO ADMINISTRATIVO 20' / 40' / 40'RF", "currency": "PEN",
         "factura_agent": "IMUPESA", "p_unit": 70.0, "unit": "Cntr."},
        {"concept": "REACOMODO DE STOCK", "currency": "USD",
         "factura_agent": "IMUPESA", "p_unit": 30.0, "unit": "Cntr."},
    ]},
    "MAERSK / SEALAND": {"concepts": [
        {"concept": "BOX FEE", "currency": "USD",
         "factura_agent": "IAN TAYLOR", "p_unit": 135.0, "unit": "Cntr."},
        {"concept": "CONTAINER COVERAGE FEE", "currency": "USD",
         "factura_agent": "IAN TAYLOR", "p_unit": 70.0, "unit": "Cntr."},
        {"concept": "SERVICIO INTEGRAL RECEPCIÓN DE VACÍOS", "currency": "USD",
         "factura_agent": "ALCONSA", "p_unit": 237.0, "unit": "Cntr."},
    ]},
    "MSC": {"concepts": [
        {"concept": "Despacho Contenedor", "currency": "USD",
         "factura_agent": "MSC DEL PERU", "p_unit": 167.0, "unit": "Cntr."},
        {"concept": "Despacho Documentario", "currency": "USD",
         "factura_agent": "MSC DEL PERU", "p_unit": 120.0, "unit": "BL"},
        {"concept": "VB HBL adicional", "currency": "USD",
         "factura_agent": "MSC DEL PERU", "p_unit": 105.0, "unit": "BL"},
    ]},
    "ONE": {"concepts": [
        {"concept": "Gastos Administrativos", "currency": "USD",
         "factura_agent": "MERCATOR", "p_unit": 10.0, "unit": "Factura"},
        {"concept": "Box fee", "currency": "USD",
         "factura_agent": "MERCATOR", "p_unit": 155.0, "unit": "Cntr."},
        {"concept": "SCAC", "currency": "USD",
         "factura_agent": "MERCATOR", "p_unit": 42.0, "unit": "Cntr."},
        {"concept": "Doc Fee", "currency": "USD",
         "factura_agent": "MERCATOR", "p_unit": 115.0, "unit": "BL"},
    ]},
    "PIL": {"concepts": [
        {"concept": "CONTAINER DELIVERY ORDER FEE", "currency": "USD",
         "factura_agent": "TRANSMERIDIAN", "p_unit": 125.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS", "currency": "USD",
         "factura_agent": "TRANSMERIDIAN", "p_unit": 40.0, "unit": "Factura"},
        {"concept": "SERVICIO DE ADMINISTRACIÓN DE CONTENEDORES", "currency": "USD",
         "factura_agent": "TRANSMERIDIAN", "p_unit": 36.0, "unit": "Cntr."},
        {"concept": "DOC FEE", "currency": "USD",
         "factura_agent": "TRANSMERIDIAN", "p_unit": 120.0, "unit": "BL"},
    ]},
    "SEABOARD": {"concepts": [
        {"concept": "CONTAINER DELIVERY ORDER FEE", "currency": "USD",
         "factura_agent": "CITIKOLD", "p_unit": 116.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS", "currency": "USD",
         "factura_agent": "CITIKOLD", "p_unit": 30.0, "unit": "Factura"},
        {"concept": "DOC FEE", "currency": "USD",
         "factura_agent": "CITIKOLD", "p_unit": 140.98, "unit": "BL"},
    ]},
    "WAN HAI": {"concepts": [
        {"concept": "CONTROL & ADMINISTRACION DE CONTENEDORES", "currency": "USD",
         "factura_agent": "TRANSTOTAL", "p_unit": 50.0, "unit": "Cntr."},
        {"concept": "BOX FEE", "currency": "USD",
         "factura_agent": "TRANSTOTAL", "p_unit": 100.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS", "currency": "USD",
         "factura_agent": "TRANSTOTAL", "p_unit": 20.0, "unit": "Factura"},
        {"concept": "DOC FEE", "currency": "USD",
         "factura_agent": "TRANSTOTAL", "p_unit": 108.0, "unit": "BL"},
    ]},
    "YANG MING": {"concepts": [
        {"concept": "Container Delivery & Control Fee", "currency": "USD",
         "factura_agent": "PMA", "p_unit": 180.0, "unit": "Cntr."},
        {"concept": "Equipment Services Fee", "currency": "USD",
         "factura_agent": "PMA", "p_unit": 36.0, "unit": "Cntr."},
        {"concept": "Administration Fee", "currency": "USD",
         "factura_agent": "PMA", "p_unit": 40.0, "unit": "Factura"},
        {"concept": "Documentation Fee", "currency": "USD",
         "factura_agent": "PMA", "p_unit": 80.0, "unit": "BL"},
    ]},
    "ZIM": {"concepts": [
        {"concept": "DELIVERY ORDER", "currency": "USD",
         "factura_agent": "COSMOS", "p_unit": 200.0, "unit": "Cntr."},
        {"concept": "GASTOS ADMINISTRATIVOS", "currency": "USD",
         "factura_agent": "COSMOS", "p_unit": 30.0, "unit": "Factura"},
        {"concept": "Documentation Fee", "currency": "USD",
         "factura_agent": "COSMOS", "p_unit": 150.0, "unit": "BL"},
    ]},
}


def get_g_locales_data() -> dict:
    return G_LOCALES_DATA


def get_mbl_data() -> dict:
    return MBL_DATA


def get_vb_importacion_data() -> dict:
    return VB_IMPORTACION_DATA
