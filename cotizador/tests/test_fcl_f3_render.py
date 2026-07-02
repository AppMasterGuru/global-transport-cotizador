"""
Abel F3 render fixes (2026-07-02) — regression guards.

Item 1: the payment condition suffix "(COLLECT)"/"(PREPAID)" never reaches a
client-facing concept label. Data model (venta_json description + is_collect)
keeps it; every render surface strips it: proforma ES/EN (pdf_generator table
builders) and quote_detail (concept_label Jinja filter).

Item 3: EXPO FOB agente omitted a flete internacional concept entirely (its
registry items are all local), so the proforma dropped the whole "Costos de
Flete Internacional" section. The FCL FOB EXPO tariff sheet carries an
"Ocean Freight" row (COLLECT, 0) same as EXW — structure only. Every FCL
agente incoterm's proforma must render the flete section; USD 0.00 is a valid
render, never a reason to suppress.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_PATH", _tmp_db.name)

from core.db import get_connection, init_db  # noqa: E402
from core.fcl_agente_incoterm import get_incoterm_concepts  # noqa: E402
from core.pdf_generator import render_html, strip_payment_suffix  # noqa: E402


# ── Item 1: label strip ───────────────────────────────────────────────────────

class TestStripPaymentSuffix:
    @pytest.mark.parametrize("raw,expected", [
        ("Flete Internacional (COLLECT)", "Flete Internacional"),
        ("Flete Internacional (PREPAID)", "Flete Internacional"),
        ("Flete Internacional (collect)", "Flete Internacional"),
        ("Flete Internacional", "Flete Internacional"),
        ("Visto Bueno", "Visto Bueno"),
        ("", ""),
    ])
    def test_strip(self, raw, expected):
        assert strip_payment_suffix(raw) == expected

    def test_only_suffix_position_stripped(self):
        # A parenthesised term mid-name is not a payment condition.
        assert strip_payment_suffix("THC (COLLECT) Extra") == "THC (COLLECT) Extra"


# ── Item 3: registry structure ────────────────────────────────────────────────

class TestFobFleteConcept:
    def test_fob_emits_flete_internacional(self):
        concepts = get_incoterm_concepts("EXPO", "FOB")
        flete = [c for c in concepts if "flete internacional" in c.description.lower()]
        assert flete, "EXPO FOB must emit a Flete Internacional concept (tariff sheet structure)"
        c = flete[0]
        assert c.is_international is True
        assert c.igv_applicable is False
        assert c.is_collect is True
        assert c.amount_usd == 0.0

    def test_all_four_incoterms_have_an_international_concept(self):
        # The proforma flete section renders iff >=1 international item exists —
        # every registered incoterm must therefore carry at least one.
        for flujo, inc in [("EXPO", "EXW"), ("EXPO", "FOB"),
                           ("IMPO", "DAP"), ("IMPO", "DDP")]:
            concepts = get_incoterm_concepts(flujo, inc)
            assert any(c.is_international for c in concepts), f"{flujo} {inc}"


# ── End-to-end: POST each agente incoterm, render every surface ──────────────

@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS provider_replies;
            DROP TABLE IF EXISTS credit_registry;
        """)
    init_db()
    yield


@pytest.fixture
def client():
    from api.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    with a.test_client() as c:
        yield c


_BASE = {
    "client_name": "F3 Render SA",
    "client_email": "f3@test.com",
    "mode": "fcl",
    "client_type": "agente_internacional",
    "cargo_description": "cargo",
    "weight": "18000",
    "weight_unit": "kg",
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "agente",
    "fcl_terminal": "DPW",
    "fcl_container_type": "20STD",
    "num_containers": "1",
    "margin_pct": "20",
}

_PER_INCOTERM = {
    "EXW": {"operation": "exportacion", "incoterm": "EXW",
            "origin": "Callao, Peru", "destination": "Hamburg, Germany",
            "fcl_naviera": "CMA CGM"},
    "FOB": {"operation": "exportacion", "incoterm": "FOB",
            "origin": "Callao, Peru", "destination": "Hamburg, Germany",
            "fcl_naviera": "CMA CGM"},
    "DAP": {"operation": "importacion", "incoterm": "DAP",
            "origin": "Shanghai, China", "destination": "Callao, Peru",
            "fcl_naviera": "CMA CGM / APL"},
    "DDP": {"operation": "importacion", "incoterm": "DDP",
            "origin": "Shanghai, China", "destination": "Callao, Peru",
            "fcl_naviera": "CMA CGM / APL",
            "invoice_usd": "50000", "insurance_usd": "500",
            "flete_lcl": "2000"},
}


def _create(client, incoterm):
    from urllib.parse import unquote
    resp = client.post("/quote/new", data={**_BASE, **_PER_INCOTERM[incoterm]},
                       follow_redirects=False)
    assert resp.status_code == 302, resp.data
    loc = resp.headers["Location"]
    ref = unquote(loc.rstrip("/").split("/quote/")[-1])
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM quotes WHERE reference_code = ?",
                           (ref,)).fetchone()
    return dict(row), loc


def _proforma(row, lang):
    venta = json.loads(row["venta_json"])
    meta = {
        "reference": row["reference_code"], "client_name": row["client_name"],
        "origin": row["origin"], "destination": row["destination"],
        "incoterm": row["incoterm"], "mode": row["mode"],
        "language": lang, "staff_code": row["staff_code"],
        "exchange_rate": 3.75,
        "invoice_usd": 50000, "insurance_usd": 500, "freight_usd": 2000,
    }
    return render_html(venta, meta)


_SECTION_HDR = {"es": "Costos de Flete Internacional",
                "en": "International Freight Charges"}


class TestProformaFleteSectionAllIncoterms:
    @pytest.mark.parametrize("incoterm", ["EXW", "FOB", "DAP", "DDP"])
    @pytest.mark.parametrize("lang", ["es", "en"])
    def test_flete_section_renders(self, client, incoterm, lang):
        row, _ = _create(client, incoterm)
        html = _proforma(row, lang)
        assert _SECTION_HDR[lang] in html, (
            f"{incoterm}/{lang}: proforma must contain the flete section"
        )

    @pytest.mark.parametrize("incoterm", ["EXW", "FOB"])
    def test_collect_zero_line_renders_plain_label(self, client, incoterm):
        # 0.00 collect freight renders as a plain "Flete Internacional" row.
        row, _ = _create(client, incoterm)
        html = _proforma(row, "es")
        assert "Flete Internacional" in html
        assert "(COLLECT)" not in html and "(PREPAID)" not in html
        assert "USD 0.00" in html

    @pytest.mark.parametrize("incoterm", ["EXW", "FOB", "DAP", "DDP"])
    def test_no_payment_suffix_either_language(self, client, incoterm):
        row, _ = _create(client, incoterm)
        for lang in ("es", "en"):
            html = _proforma(row, lang)
            assert "(COLLECT)" not in html and "(PREPAID)" not in html

    def test_data_model_keeps_collect_marker(self, client):
        # Item 1 strips DISPLAY only — venta_json keeps the full description.
        row, _ = _create(client, "EXW")
        venta = json.loads(row["venta_json"])
        descs = [i["description"] for i in venta["line_items"]]
        assert "Flete Internacional (COLLECT)" in descs


class TestQuoteDetailSurface:
    @pytest.mark.parametrize("incoterm", ["EXW", "FOB"])
    def test_detail_page_strips_suffix_and_shows_flete(self, client, incoterm):
        _, loc = _create(client, incoterm)
        page = client.get(loc).data.decode()
        assert "(COLLECT)" not in page and "(PREPAID)" not in page
        assert "Flete Internacional" in page
