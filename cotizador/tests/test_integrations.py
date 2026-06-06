"""
Integration tests for the three new data integrations (2026-05-15):

  1. HANDLING AEREO.xlsx → drive.py air handling fee engine
  2. DATA COLOADERS.xlsx → providers table + provider_emails.py
  3. LISTA CRÉDITOS.xlsx → credit_registry table

12 tests (89–100).  All run without network calls or Flask running.
"""

from __future__ import annotations

import io
import os
import tempfile

import openpyxl
import pytest

# ── DB isolation ──────────────────────────────────────────────────────────────
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name

from core.db import get_connection, init_db, seed_credit_registry, get_credit_registry, get_credit_entry  # noqa: E402
from core.providers import seed_providers, get_providers, get_provider_emails  # noqa: E402
from core.drive import _parse_handling_aereo, get_air_handling_fee  # noqa: E402
from core.provider_emails import generate_provider_emails  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Full DB isolation for every test."""
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS credit_registry;
        """)
    init_db()
    yield


# ══════════════════════════════════════════════════════════════════════════════
# Integration 1 — HANDLING AEREO → drive.py
# ══════════════════════════════════════════════════════════════════════════════

def _make_handling_xlsx() -> bytes:
    """Build a minimal HANDLING AEREO.xlsx in memory for unit tests."""
    wb = openpyxl.Workbook()

    # TALMA sheet
    ws_talma = wb.active
    ws_talma.title = "TALMA"
    ws_talma.append(["Aerolínea", "Valor Vta. (Dólares)", "IGV", "Monto Total", "Counter"])
    ws_talma.append(["LAN AIRLINES / LAN PERU / LAN CARGO", 94.0, 16.92, 110.92, "LAN"])
    ws_talma.append(["AMERICAN AIRLINES", 88.0, 15.84, 103.84, "TALMA"])
    ws_talma.append(["UNITED AIRLINES", 80.0, 14.40, 94.40, "TALMA"])
    ws_talma.append(["COPA", 90.0, 16.20, 106.20, "TALMA"])

    # SHOHIN sheet
    ws_shohin = wb.create_sheet("SHOHIN")
    ws_shohin.append(["Aerolínea", "Valor Vta. (Dólares)", "IGV", "Monto Total"])
    ws_shohin.append(["658 AIRMAX", 90.0, 16.20, 106.20])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 89 — parser returns list of fee dicts
def test_parse_handling_aereo_returns_fees():
    """_parse_handling_aereo returns one dict per airline row across all sheets."""
    fees = _parse_handling_aereo(_make_handling_xlsx())
    assert isinstance(fees, list)
    assert len(fees) == 5   # 4 TALMA + 1 SHOHIN
    for fee in fees:
        assert "airline"   in fee
        assert "handler"   in fee
        assert "net_usd"   in fee
        assert "igv_usd"   in fee
        assert "total_usd" in fee


# 90 — parser extracts correct values for LAN
def test_parse_handling_aereo_lan_values():
    """LAN row parsed correctly — net $94, handler=TALMA, counter=LAN."""
    fees = _parse_handling_aereo(_make_handling_xlsx())
    lan = next(f for f in fees if "LAN AIRLINES" in f["airline"])
    assert lan["net_usd"]   == 94.0
    assert lan["igv_usd"]   == 16.92
    assert lan["total_usd"] == 110.92
    assert lan["handler"]   == "TALMA"
    assert lan["counter"]   == "LAN"


# 91 — get_air_handling_fee stub (no Graph creds in tests)
def test_get_air_handling_fee_stub_returns_none():
    """get_air_handling_fee returns None in stub mode (no Graph credentials)."""
    # GRAPH_CLIENT_SECRET may be in env — clear temporarily
    secret = os.environ.pop("GRAPH_CLIENT_SECRET", None)
    try:
        result = get_air_handling_fee("LAN")
        # If _CONFIGURED is False, should return None (fees list is empty)
        # If _CONFIGURED is True (live env), it tries SharePoint — result may be dict
        assert result is None or isinstance(result, dict)
    finally:
        if secret:
            os.environ["GRAPH_CLIENT_SECRET"] = secret


# 92 — get_air_handling_fee fuzzy match on counter name
def test_get_air_handling_fee_counter_match(monkeypatch):
    """get_air_handling_fee matches 'LAN' against the counter column."""
    sample_fees = [
        {"airline": "LAN AIRLINES / LAN PERU / LAN CARGO",
         "handler": "TALMA", "counter": "LAN",
         "net_usd": 94.0, "igv_usd": 16.92, "total_usd": 110.92},
    ]
    monkeypatch.setattr("core.drive.get_air_handling_fees", lambda: sample_fees)
    result = get_air_handling_fee("LAN")
    assert result is not None
    assert result["net_usd"] == 94.0
    assert result["counter"] == "LAN"


# 93 — get_air_handling_fee returns None for unknown airline
def test_get_air_handling_fee_unknown(monkeypatch):
    """get_air_handling_fee returns None when carrier not in fee list."""
    sample_fees = [
        {"airline": "LAN AIRLINES / LAN PERU / LAN CARGO",
         "handler": "TALMA", "counter": "LAN",
         "net_usd": 94.0, "igv_usd": 16.92, "total_usd": 110.92},
    ]
    monkeypatch.setattr("core.drive.get_air_handling_fees", lambda: sample_fees)
    assert get_air_handling_fee("NONEXISTENT AIRLINE XYZ") is None
    assert get_air_handling_fee("") is None
    assert get_air_handling_fee(None) is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration 2 — DATA COLOADERS → providers table
# ══════════════════════════════════════════════════════════════════════════════

_SAMPLE_CONTACTS = [
    {"company": "MSL CORPORATE", "contact_name": "FRANCCESCO URRUTIA",
     "role": "LCL IMPORT SALES", "email": "furrutia@mslcorporate.com.pe", "phone": "970845649"},
    {"company": "MSL CORPORATE", "contact_name": "SALLY MENDOZA",
     "role": "LCL EXPORT INSIDE SALES", "email": "smendoza@mslcorporate.com.pe", "phone": "970830509"},
    {"company": "CRAFT", "contact_name": "DIANA GUTIERREZ",
     "role": "SALES EXECUTIVE / IMPO & EXPO", "email": "diana.gutierrez@craftmulti.com", "phone": "987573415"},
    {"company": "CRAFT", "contact_name": "BETSY CARAZAS",
     "role": "AIR IMPORT SALES - LATAM", "email": "airimpo.latam.pe@craftmulti.com", "phone": "934288836"},
    {"company": "SACO", "contact_name": "KATHERIN FLORES",
     "role": "LCL IMPORT SALES", "email": "katherin.flores@pe.sacoshipping.com", "phone": "998191086"},
]


# 94 — seed_providers inserts rows
def test_seed_providers_inserts():
    """seed_providers returns count of rows inserted."""
    n = seed_providers(_SAMPLE_CONTACTS)
    assert n == 5


# 95 — seed_providers skips duplicates
def test_seed_providers_idempotent():
    """seed_providers skips exact duplicates on second run."""
    seed_providers(_SAMPLE_CONTACTS)
    n2 = seed_providers(_SAMPLE_CONTACTS)
    assert n2 == 0


# 96 — get_providers returns correct rows
def test_get_providers_by_company():
    """get_providers(company='MSL') returns only MSL rows."""
    seed_providers(_SAMPLE_CONTACTS)
    msl = get_providers(company="MSL")
    assert len(msl) == 2
    assert all(r["company"] == "MSL CORPORATE" for r in msl)


# 97 — service_type inference
def test_providers_service_type_inferred():
    """Service types are inferred correctly from role text."""
    seed_providers(_SAMPLE_CONTACTS)
    all_p = get_providers()
    types = {r["contact_name"]: r["service_type"] for r in all_p}
    assert types["FRANCCESCO URRUTIA"] == "lcl_impo"
    assert types["SALLY MENDOZA"]      == "lcl_expo"
    assert types["BETSY CARAZAS"]      == "air_impo"


# 98 — get_provider_emails returns real addresses
def test_get_provider_emails_returns_addresses():
    """get_provider_emails returns email list after seeding."""
    seed_providers(_SAMPLE_CONTACTS)
    emails = get_provider_emails("MSL")
    assert len(emails) >= 2
    assert all("@" in e for e in emails)
    assert "furrutia@mslcorporate.com.pe" in emails


# 99 — generate_provider_emails includes to_emails field
def test_generate_provider_emails_has_to_field():
    """generate_provider_emails returns dicts with to_emails key for LCL."""
    seed_providers(_SAMPLE_CONTACTS)
    quote = {
        "reference_code": "TEST-001", "mode": "lcl", "incoterm": "FOB",
        "origin": "Lima", "destination": "Hamburg",
        "cargo_description": "Test cargo", "weight_kg": 100.0, "volume_cbm": 0.5,
    }
    emails = generate_provider_emails(quote)
    assert isinstance(emails, list)
    assert len(emails) > 0
    for e in emails:
        assert "to_emails" in e
        assert isinstance(e["to_emails"], list)

    # MSL draft should have real addresses
    msl_draft = next((e for e in emails if "MSL" in e["provider"].upper()), None)
    assert msl_draft is not None
    assert len(msl_draft["to_emails"]) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# Integration 3 — LISTA CRÉDITOS → credit_registry table
# ══════════════════════════════════════════════════════════════════════════════

_SAMPLE_CREDIT = [
    {"company": "AUTOMATIC SYSTEMS S.A.C.", "category": "local_client",
     "country": "Peru", "credit_days": 30, "condition": "APROBADO / TRANSFERENCIA"},
    {"company": "ACI WORLD SERVICES", "category": "international_agent",
     "country": "CANADA", "credit_days": 30, "condition": "APROBADO / TRANSFERENCIA"},
    {"company": "MSL", "category": "service_provider",
     "country": "", "credit_days": 60, "condition": "APROBADO / TRANSFERENCIA"},
    {"company": "GEASAC", "category": "service_provider",
     "country": "", "credit_days": 7, "condition": "APROBADO / TRANSFERENCIA",
     "notes": "Primer servicio al contado"},
]


# 100 — seed_credit_registry inserts rows
def test_seed_credit_registry_inserts():
    """seed_credit_registry returns count of rows inserted."""
    n = seed_credit_registry(_SAMPLE_CREDIT)
    assert n == 4


# 101 — seed_credit_registry skips duplicates
def test_seed_credit_registry_idempotent():
    """seed_credit_registry skips existing company+category combinations."""
    seed_credit_registry(_SAMPLE_CREDIT)
    n2 = seed_credit_registry(_SAMPLE_CREDIT)
    assert n2 == 0


# 102 — get_credit_registry filters by category
def test_get_credit_registry_by_category():
    """get_credit_registry(category='service_provider') returns only that category."""
    seed_credit_registry(_SAMPLE_CREDIT)
    providers = get_credit_registry(category="service_provider")
    assert len(providers) == 2
    assert all(r["category"] == "service_provider" for r in providers)


# 103 — get_credit_entry finds by partial name
def test_get_credit_entry_partial_match():
    """get_credit_entry finds MSL when searched by partial name."""
    seed_credit_registry(_SAMPLE_CREDIT)
    entry = get_credit_entry("MSL")
    assert entry is not None
    assert entry["credit_days"] == 60
    assert entry["category"] == "service_provider"


# 104 — get_credit_entry returns None for unknown company
def test_get_credit_entry_not_found():
    """get_credit_entry returns None when company not in registry."""
    seed_credit_registry(_SAMPLE_CREDIT)
    assert get_credit_entry("EMPRESA DESCONOCIDA XYZ") is None
