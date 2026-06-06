"""
Smart warnings for quote review.

check_quote_warnings(quote_dict) → list of {level, code, message}

level "red"    → blocks the Aprobar button
level "yellow" → shows advisory, does not block

Called by the quote_detail route before rendering so warnings
are computed server-side and passed to the template.
"""

from __future__ import annotations

import json
import re


def _parse_json_field(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def check_quote_warnings(quote: dict) -> list[dict]:
    """
    Evaluate all warning rules against a quote dict.
    The dict is expected to have JSON fields already parsed
    (as returned by _row_to_dict in routes.py), but this
    function handles raw JSON strings too.
    """
    warnings: list[dict] = []

    def warn(level: str, code: str, message: str) -> None:
        warnings.append({"level": level, "code": code, "message": message})

    venta  = _parse_json_field(quote.get("venta_json"))
    costeo = _parse_json_field(quote.get("costeo_json"))

    margin      = float(quote.get("margin_pct") or 0.0)
    cargo_desc  = (quote.get("cargo_description") or "").lower()
    client_name = (quote.get("client_name") or "").lower()
    weight_kg   = float(quote.get("weight_kg") or 0.0)
    cbm         = float(quote.get("volume_cbm") or 0.0)

    # ── 1. Margin floor ───────────────────────────────────────────────────────
    if margin < 0.20:
        warn("yellow", "MARGIN_BELOW_FLOOR", "Margen por debajo del mínimo (20%) — JP puede aprobar")
    elif margin < 0.25:
        warn("yellow", "MARGIN_LOW",         "Margen ajustado — revisar antes de aprobar")

    # ── 2. Dangerous goods without UN/IATA code ───────────────────────────────
    _dangerous_kw = ["peligrosa", "peligroso", "dangerous", "hazmat",
                     "mercancía peligrosa", "carga peligrosa", "dg cargo"]
    is_dangerous  = any(kw in cargo_desc for kw in _dangerous_kw)
    has_un_code   = (
        "un " in cargo_desc
        or "iata" in cargo_desc
        or bool(re.search(r"\bun\s?\d{4}\b", cargo_desc, re.IGNORECASE))
    )
    if is_dangerous and not has_un_code:
        warn("red", "DANGEROUS_NO_UN_CODE",
             "Carga peligrosa sin código UN/IATA — requerido antes de cotizar")

    # ── 3. Perishable without cold-chain confirmation ─────────────────────────
    _perishable_kw = ["perecible", "perishable", "fresco", "congelado",
                      "refrigerado", "orgánico", "flores", "frutas", "verduras"]
    is_perishable  = any(kw in cargo_desc for kw in _perishable_kw)
    has_temp_info  = any(t in cargo_desc for t in [
        "temperatura", "°c", "celsius", "cadena de frío",
        "cold chain", "refrigerado", "reefer", "-18", "+2", "+4"
    ])
    if is_perishable and not has_temp_info:
        warn("yellow", "PERISHABLE_NO_TEMP",
             "Perecible — confirmar cadena de frío y requisitos de temperatura")

    # ── 4. Farmex without OEA+BASC customs agent ──────────────────────────────
    is_farmex      = "farmex" in client_name
    customs_agent  = (costeo.get("customs_agent") or "").lower()
    uses_oea_basc  = "oea" in customs_agent or "basc" in customs_agent
    if is_farmex and not uses_oea_basc:
        warn("red", "FARMEX_NO_BASC",
             "Farmex requiere agente OEA+BASC — seleccionar agente certificado")

    # ── 5. No client email ────────────────────────────────────────────────────
    client_email = (quote.get("client_email") or "").strip()
    if not client_email:
        warn("yellow", "NO_CLIENT_EMAIL",
             "Sin email de cliente — no se podrá enviar la cotización automáticamente")

    # ── 6. Cargo density checks ───────────────────────────────────────────────
    if weight_kg > 0 and cbm > 0:
        density = weight_kg / cbm
        if density > 2000:
            warn("yellow", "HIGH_DENSITY",
                 f"Densidad muy alta ({density:.0f} kg/m³) — verificar dimensiones")
        elif density < 50:
            warn("yellow", "LOW_DENSITY",
                 f"Densidad muy baja ({density:.0f} kg/m³) — verificar dimensiones")

    # ── 7. Zero venta total ───────────────────────────────────────────────────
    venta_total = venta.get("total_usd") or 0
    if not venta_total:
        warn("red", "ZERO_VENTA", "Total de venta es cero — verificar tarifas")

    # ── 8. Zero flete internacional ───────────────────────────────────────────
    flete = costeo.get("flete_internacional_usd") or 0
    if flete == 0:
        warn("yellow", "ZERO_FLETE",
             "Flete internacional en cero — confirmar tarifa con proveedor")

    return warnings


def has_red_warnings(warnings: list[dict]) -> bool:
    return any(w["level"] == "red" for w in warnings)
