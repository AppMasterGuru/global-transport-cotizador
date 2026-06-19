"""
FCL import local costs by naviera — Abel Parte 2 (2026-06-19).

Abel's explicit written rule: FCL import charges only THC + ISPS + MBL
emission. Parsed (not hardcoded) from
"Gastos de Importacion en Callao por Naviera.xlsx" (Client Data/Part 2_Abel/):
  - G. LOCALES sheet  -> THCD (20'/40') + an "adicional" concept (usually
    ISPS, sometimes DOC FEE) at 20'/40'.
  - EMISION MBL sheet -> free-text MBL emission cost per naviera (mixed
    USD/PEN, mixed "+ IGV" / flat / "NO COBRA" formats).

HOLD (TODO abel-Q3): there is a second import structure — the EXPO_IMPO
IMPORTACIÓN sheet's "VB IMPORTACION" layer — that may stack with or
replace the costs here. NOT wired into the import total this session;
default to Abel's written THC+ISPS+MBL-only rule.
"""

from __future__ import annotations

import re

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


def get_fcl_import_local_costs(g_locales: dict, mbl: dict, naviera: str) -> dict | None:
    """
    Combine THC + ISPS/adicional + MBL for one naviera — Abel's explicit
    THC+ISPS+MBL-only rule. Returns None if the naviera isn't found in
    G. LOCALES (the THC/ISPS source).
    """
    g = g_locales.get(naviera)
    if g is None:
        return None
    m = _lookup_mbl(mbl, naviera)
    override = _NAVIERA_OVERRIDES.get(naviera, {})
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
    }
