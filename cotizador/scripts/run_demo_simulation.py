#!/usr/bin/env python3
"""
Demo simulation — GT Cotizador
Runs 3 realistic quotes end-to-end using the same core logic as the live app.

Quotes:
  1  LCL   EXW  Lima → Hamburg          Hamburg Importer GmbH     GT-PC  (Abel)    ES
  2  Aéreo EXW  Lima → LAX              Miami Foods Corp          GT-LOG (Daniella) EN
  3  FCL   DAP  Manzanillo → Callao     Distribuidora Lima SAC    RENATO            ES

Each quote is verified:
  - costeo / venta / margin computed
  - provider emails generated
  - SINTAD export tested (APPROVED quotes only)

Results saved to: scripts/demo_simulation_results.json

Usage:
    cd cotizador
    source .venv/bin/activate
    python scripts/run_demo_simulation.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Project root on path ──────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env (SharePoint creds, SBS key, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # dotenv optional — env vars may already be set

# ── DB init before any core imports ──────────────────────────────────────────
from core.db import audit, get_connection, init_db, transition_status  # noqa: E402

init_db()

from core.exchange_rate import get_exchange_rate, soles_to_usd  # noqa: E402
from core.provider_emails import generate_provider_emails       # noqa: E402
from core.reference import generate_reference                   # noqa: E402
from core.sintad_export import generate_sintad_excel            # noqa: E402
from core.transport import (                                     # noqa: E402
    calculate_transport,
    customs_total_usd,
    get_consolidator,
    get_customs_agent,
    visto_bueno_total_usd,
)
from core.drive import get_air_handling_fee                     # noqa: E402
from config.signatures import get_signature                     # noqa: E402

MARGIN_FLOOR = 0.10
DEMO_ACTOR   = "demo-simulation"

# ── Quote definitions ─────────────────────────────────────────────────────────

QUOTES = [
    {
        "client_name":       "Hamburg Importer GmbH",
        "client_email":      "import@hamburg-importer.de",
        "incoterm":          "EXW",
        "mode":              "lcl",
        "origin":            "Lima, Perú",
        "destination":       "Hamburgo, Alemania",
        "cargo_description": "Uvas frescas — refrigeradas, perecibles",
        "weight_kg":         850.0,
        "volume_cbm":        3.2,
        "flete_usd":         275.0,   # representative LCL rate Lima→Hamburg
        "consolidator":      "CRAFT",
        "airline":           "",
        "requires_oea_basc": False,
        "margin_pct":        0.22,
        "staff_code":        "GT-PC",
        "language":          "es",
        "label":             "Quote 1 — LCL Lima→Hamburg (PENDING)",
    },
    {
        "client_name":       "Miami Foods Corp",
        "client_email":      "logistics@miamifoods.com",
        "incoterm":          "EXW",
        "mode":              "aereo",
        "origin":            "Lima, Perú",
        "destination":       "Los Angeles, CA, USA",
        "cargo_description": "Espárragos frescos — perecibles, temperatura controlada",
        "weight_kg":         240.0,
        "volume_cbm":        1.1,
        "flete_usd":         1200.0,  # representative air freight Lima→LAX
        "consolidator":      "",
        "airline":           "LAN Airlines",
        "requires_oea_basc": False,
        "margin_pct":        0.20,
        "staff_code":        "GT-LOG",
        "language":          "en",
        "label":             "Quote 2 — Aéreo Lima→LAX (APPROVED)",
    },
    {
        "client_name":       "Distribuidora Lima SAC",
        "client_email":      "importaciones@distribuidoralima.pe",
        "incoterm":          "DAP",
        "mode":              "fcl",
        "origin":            "Manzanillo, México",
        "destination":       "Callao, Perú",
        "cargo_description": "Maquinaria industrial — 40'HC, carga pesada",
        "weight_kg":         18500.0,
        "volume_cbm":        67.3,    # 40'HC ≈ 67 CBM
        "flete_usd":         2800.0,  # representative FCL 40'HC Manzanillo→Callao
        "consolidator":      "",
        "airline":           "",
        "requires_oea_basc": False,
        "margin_pct":        0.18,
        "staff_code":        "RENATO",
        "language":          "es",
        "label":             "Quote 3 — FCL Manzanillo→Callao (SENT)",
    },
]

# ── Core calculation (mirrors create_quote in routes.py) ─────────────────────

def build_quote(spec: dict, exchange_rate: float) -> tuple[dict, dict, dict, float, float]:
    """
    Returns (costeo, venta, transport_result, costeo_total, venta_total).
    Mirrors the calculation logic in routes.py create_quote().
    """
    mode      = spec["mode"]
    weight_kg = spec["weight_kg"]
    cbm       = spec["volume_cbm"]
    flete_usd = spec["flete_usd"]

    # Transport
    transport_result  = calculate_transport(weight_kg, cbm)
    transport_soles   = transport_result["charge_soles"]
    transport_usd     = soles_to_usd(transport_soles, exchange_rate)

    # Customs agent
    agent       = get_customs_agent(spec["requires_oea_basc"])
    customs_usd = customs_total_usd(agent)

    # Visto bueno (LCL only)
    vb_usd            = 0.0
    consolidator_info = {}
    if mode == "lcl" and spec["consolidator"]:
        try:
            consolidator_info = get_consolidator(spec["consolidator"])
            vb_usd = visto_bueno_total_usd(consolidator_info)
        except ValueError:
            pass  # unknown consolidator → no visto bueno (same as route flash)

    # Air handling fee (aereo only)
    handling_aereo_usd  = 0.0
    handling_aereo_info: dict = {}
    if mode == "aereo" and spec.get("airline"):
        fee = get_air_handling_fee(spec["airline"])
        if fee:
            handling_aereo_usd  = fee["net_usd"]
            handling_aereo_info = fee

    costeo_total = flete_usd + vb_usd + customs_usd + transport_usd + handling_aereo_usd
    margin_pct   = max(spec["margin_pct"], MARGIN_FLOOR)
    venta_total  = costeo_total * (1 + margin_pct)

    costeo = {
        "flete_internacional_usd": flete_usd,
        "visto_bueno_usd":         vb_usd,
        "handling_aereo_usd":      handling_aereo_usd,
        "handling_aereo_detail":   handling_aereo_info,
        "customs_agent_usd":       customs_usd,
        "transport_usd":           transport_usd,
        "transport_soles":         transport_soles,
        "transport_detail":        transport_result,
        "total_usd":               round(costeo_total, 2),
        "exchange_rate":           exchange_rate,
        "consolidator":            spec["consolidator"] if mode == "lcl" else None,
        "airline":                 spec["airline"] if mode == "aereo" else None,
        "customs_agent":           agent["name"],
    }

    venta_items = [
        {
            "description": "International Freight",
            "quantity":    1,
            "unit_price":  round(flete_usd, 2),
            "total":       round(flete_usd, 2),
        },
        {
            "description": "Handling & Port Fees",
            "quantity":    1,
            "unit_price":  round(vb_usd + customs_usd + handling_aereo_usd, 2),
            "total":       round(vb_usd + customs_usd + handling_aereo_usd, 2),
        },
        {
            "description": "Local Transport",
            "quantity":    1,
            "unit_price":  round(transport_usd, 2),
            "total":       round(transport_usd, 2),
        },
    ]

    venta = {
        "line_items":   venta_items,
        "total_usd":    round(venta_total, 2),
        "margin_pct":   margin_pct,
        "validity_days": 15,
    }

    return costeo, venta, transport_result, costeo_total, venta_total


def insert_quote(spec: dict, costeo: dict, venta: dict, exchange_rate: float) -> tuple[str, int]:
    """Insert quote into DB, return (reference_code, quote_id)."""
    with get_connection() as conn:
        ref = generate_reference(conn, spec["client_name"], spec["incoterm"], spec["staff_code"])
        result = conn.execute(
            """
            INSERT INTO quotes
              (reference_code, client_name, client_email, incoterm, mode,
               origin, destination, cargo_description,
               weight_kg, volume_cbm, dimensions_json,
               costeo_json, venta_json, margin_pct, exchange_rate,
               status, staff_code, language)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,?)
            """,
            (
                ref,
                spec["client_name"],
                spec["client_email"],
                spec["incoterm"],
                spec["mode"],
                spec["origin"],
                spec["destination"],
                spec["cargo_description"],
                spec["weight_kg"],
                spec["volume_cbm"],
                json.dumps({"l": 0, "w": 0, "h": 0, "qty": 1}),
                json.dumps(costeo),
                json.dumps(venta),
                max(spec["margin_pct"], MARGIN_FLOOR),
                exchange_rate,
                spec["staff_code"],
                spec["language"],
            ),
        )
        conn.commit()
        quote_id = result.lastrowid
    return ref, quote_id


# ── Verification checks ───────────────────────────────────────────────────────

def verify_quote(
    spec: dict,
    ref: str,
    costeo: dict,
    venta: dict,
    costeo_total: float,
    venta_total: float,
) -> list[str]:
    """Return list of failed checks (empty = all pass)."""
    failures = []

    if costeo_total <= 0:
        failures.append(f"costeo_total = {costeo_total} (must be > 0)")
    if venta_total <= costeo_total:
        failures.append(f"venta_total {venta_total:.2f} not > costeo_total {costeo_total:.2f}")
    actual_margin = (venta_total - costeo_total) / costeo_total
    if actual_margin < MARGIN_FLOOR - 0.001:
        failures.append(f"margin {actual_margin:.1%} below floor {MARGIN_FLOOR:.0%}")
    if not ref:
        failures.append("reference_code empty")
    if costeo.get("total_usd", 0) != round(costeo_total, 2):
        failures.append("costeo.total_usd mismatch")
    if venta.get("total_usd", 0) != round(venta_total, 2):
        failures.append("venta.total_usd mismatch")

    return failures


def check_provider_emails(ref: str) -> tuple[int, list[str]]:
    """Generate provider emails and return (count, issues)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    if row is None:
        return 0, ["quote not found in DB"]

    quote = dict(row)
    for field in ("costeo_json", "venta_json", "dimensions_json"):
        raw = quote.get(field)
        if raw and isinstance(raw, str):
            try:
                quote[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass

    issues = []
    try:
        emails = generate_provider_emails(quote)
        count = len(emails)
        if count == 0:
            issues.append("no provider emails generated")
    except Exception as exc:
        count = 0
        issues.append(f"provider_emails error: {exc}")
    return count, issues


def check_sintad_export(ref: str) -> tuple[bool, list[str]]:
    """Generate SINTAD Excel and return (ok, issues)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM quotes WHERE reference_code = ?", (ref,)
        ).fetchone()
    if row is None:
        return False, ["quote not found in DB"]

    quote = dict(row)
    for field in ("costeo_json", "venta_json", "dimensions_json"):
        raw = quote.get(field)
        if raw and isinstance(raw, str):
            try:
                quote[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass

    issues = []
    try:
        xlsx_bytes = generate_sintad_excel(quote)
        if not xlsx_bytes or len(xlsx_bytes) < 100:
            issues.append(f"SINTAD Excel suspiciously small: {len(xlsx_bytes or b'')} bytes")
            return False, issues
        return True, []
    except Exception as exc:
        return False, [f"sintad_export error: {exc}"]


# ── Main runner ───────────────────────────────────────────────────────────────

def run_simulation() -> dict:
    print("\n" + "=" * 60)
    print("GT COTIZADOR — Demo Simulation")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Fetch exchange rate once — shared across all quotes
    print("\n[1/4] Fetching SBS exchange rate...")
    exchange_rate = get_exchange_rate()
    print(f"      Rate: S/{exchange_rate:.4f} per USD")

    results = []
    all_pass = True

    for i, spec in enumerate(QUOTES, 1):
        print(f"\n[{i+1}/4] {spec['label']}")
        print(f"      Client:  {spec['client_name']}")
        print(f"      Route:   {spec['origin']} → {spec['destination']}")
        print(f"      Mode:    {spec['mode'].upper()}  |  Incoterm: {spec['incoterm']}")

        result: dict = {
            "label":       spec["label"],
            "client":      spec["client_name"],
            "mode":        spec["mode"],
            "origin":      spec["origin"],
            "destination": spec["destination"],
            "checks":      {},
            "pass":        True,
        }

        # Build costeo/venta
        costeo, venta, transport_result, costeo_total, venta_total = build_quote(
            spec, exchange_rate
        )
        actual_margin = (venta_total - costeo_total) / costeo_total

        result["costeo_total_usd"]  = round(costeo_total, 2)
        result["venta_total_usd"]   = round(venta_total, 2)
        result["margin_pct"]        = round(actual_margin * 100, 1)
        result["exchange_rate"]     = exchange_rate
        result["transport_basis"]   = transport_result.get("basis", "")
        result["transport_soles"]   = transport_result.get("charge_soles", 0)

        print(f"      Costeo:  ${costeo_total:.2f} USD")
        print(f"      Venta:   ${venta_total:.2f} USD  (margin {actual_margin:.1%})")
        print(f"      Transport: S/{transport_result.get('charge_soles', 0):.0f} ({transport_result.get('basis', '?')} wins)")

        # Verify costeo/venta
        failures = verify_quote(spec, "pending", costeo, venta, costeo_total, venta_total)
        result["checks"]["costeo_venta"] = "PASS" if not failures else f"FAIL: {failures}"
        if failures:
            print(f"      [FAIL] Costeo/venta checks: {failures}")
            result["pass"] = False
            all_pass = False
        else:
            print(f"      [PASS] Costeo/venta checks")

        # Insert into DB
        try:
            ref, quote_id = insert_quote(spec, costeo, venta, exchange_rate)
            result["reference_code"] = ref
            result["quote_id"]       = quote_id
            audit("QUOTE_CREATED", ref, DEMO_ACTOR, {
                "client":           spec["client_name"],
                "mode":             spec["mode"],
                "costeo_total_usd": round(costeo_total, 2),
                "venta_total_usd":  round(venta_total, 2),
                "margin_pct":       round(actual_margin, 4),
                "simulation":       True,
            })
            result["checks"]["db_insert"] = "PASS"
            print(f"      [PASS] Inserted → {ref}")
        except Exception as exc:
            result["checks"]["db_insert"] = f"FAIL: {exc}"
            result["pass"] = False
            all_pass = False
            print(f"      [FAIL] DB insert: {exc}")
            results.append(result)
            continue

        # Provider emails
        email_count, email_issues = check_provider_emails(ref)
        if email_issues:
            result["checks"]["provider_emails"] = f"FAIL: {email_issues}"
            result["pass"] = False
            all_pass = False
            print(f"      [FAIL] Provider emails: {email_issues}")
        else:
            result["checks"]["provider_emails"] = f"PASS ({email_count} emails)"
            print(f"      [PASS] Provider emails ({email_count} generated)")
        result["provider_email_count"] = email_count

        # Transition state for Quotes 2 and 3
        if i == 2:
            # Approve Quote 2 (PENDING → APPROVED)
            transition_status(quote_id, "APPROVED", "JP-demo")
            result["final_status"] = "APPROVED"
            print(f"      Transitioned → APPROVED (approved_by: JP-demo)")
        elif i == 3:
            # Approve + Send Quote 3 (PENDING → APPROVED → SENT)
            transition_status(quote_id, "APPROVED", "JP-demo")
            transition_status(quote_id, "SENT",     "demo-sender")
            result["final_status"] = "SENT"
            print(f"      Transitioned → APPROVED → SENT")
        else:
            result["final_status"] = "PENDING"

        # SINTAD export (only for APPROVED or SENT)
        if result["final_status"] in ("APPROVED", "SENT"):
            sintad_ok, sintad_issues = check_sintad_export(ref)
            if sintad_issues:
                result["checks"]["sintad_export"] = f"FAIL: {sintad_issues}"
                result["pass"] = False
                all_pass = False
                print(f"      [FAIL] SINTAD export: {sintad_issues}")
            else:
                result["checks"]["sintad_export"] = "PASS"
                print(f"      [PASS] SINTAD export")
        else:
            result["checks"]["sintad_export"] = "SKIP (PENDING)"

        print(f"      {'✓ PASS' if result['pass'] else '✗ FAIL'} — {ref} [{result['final_status']}]")
        results.append(result)

    # ── Summary table ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SIMULATION SUMMARY")
    print("=" * 60)
    header = f"{'#':<3} {'Reference':<18} {'Mode':<8} {'Costeo':>10} {'Venta':>10} {'Margin':>8} {'Emails':>7} {'Status':<10} {'Pass?'}"
    print(header)
    print("-" * len(header))

    for i, r in enumerate(results, 1):
        ref   = r.get("reference_code", "ERROR")
        mode  = r.get("mode", "?").upper()
        cost  = f"${r.get('costeo_total_usd', 0):.0f}"
        venta = f"${r.get('venta_total_usd', 0):.0f}"
        margin = f"{r.get('margin_pct', 0):.1f}%"
        emails = str(r.get("provider_email_count", "-"))
        status = r.get("final_status", "?")
        ok     = "PASS" if r.get("pass") else "FAIL"
        print(f"{i:<3} {ref:<18} {mode:<8} {cost:>10} {venta:>10} {margin:>8} {emails:>7} {status:<10} {ok}")

    print("=" * 60)
    total_pass = sum(1 for r in results if r.get("pass"))
    print(f"Result: {total_pass}/{len(results)} quotes passed all checks")
    if all_pass:
        print("ALL CHECKS PASSED — system ready for demo")
    else:
        print("FAILURES DETECTED — review results above")
    print()

    # ── Save JSON results ─────────────────────────────────────────────────────
    output = {
        "simulation_ts":   datetime.now(timezone.utc).isoformat(),
        "exchange_rate":   exchange_rate,
        "all_pass":        all_pass,
        "pass_count":      total_pass,
        "total_count":     len(results),
        "quotes":          results,
    }

    out_path = ROOT / "scripts" / "demo_simulation_results.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Results saved → {out_path.relative_to(ROOT)}")

    return output


if __name__ == "__main__":
    run_simulation()
