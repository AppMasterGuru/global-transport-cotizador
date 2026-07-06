"""
Wire real DDP data entry: invoice_usd / insurance_usd form fields in
new_quote.html, captured by create_quote() into costeo_json, and read back
into the PDF meta dict so the duties block (cotizador/core/pdf_generator.py)
renders from REAL entered data — not injected test meta.

Freight for the CIF calc is NOT a separate new field: it reuses the
quote's already-computed flete_internacional_usd (no duplicate entry).

Full path under test: form POST -> create_quote() -> costeo_json ->
preview_pdf() meta -> render_html() -> rendered HTML.

Abel's worked example: Invoice 50,000 + Insurance 250 + Freight 6,000 = CIF 56,250
  Advalorem 5,625.00 / IGV 9,900.00 / IPM 1,237.50 / Percepcion 2,555.44 /
  Subtotal B 19,317.94
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from core.db import get_connection

_TEMPLATE = Path(__file__).parent.parent / "templates" / "new_quote.html"

_BASE_FORM = {
    "client_name": "DDP Wiring Test SA",
    "client_email": "test@ddpwiring.com",
    "mode": "fcl",
    # Ingest default flipped to agente_internacional; pin cliente_local so this
    # suite keeps exercising the cliente_local FCL path byte-for-byte.
    "client_type": "cliente_local",
    "incoterm": "DDP",
    "origin": "Shanghai, China",
    "destination": "Callao, Peru",
    "cargo_description": "DDP wiring test cargo",
    "weight": "1000",
    "weight_unit": "kg",
    "volume_cbm": "10",
    "flete_lcl": "6000.00",   # becomes flete_internacional_usd via routes.py fallback
    "staff_code": "GT-PC",
    "language": "es",
    "requester_type": "cliente",
    "margin_pct": "20",
    "invoice_usd": "50000.00",
    "insurance_usd": "250.00",
}


@pytest.fixture
def app():
    from api.app import create_app
    a = create_app()
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def _post_quote(client, overrides=None):
    data = {**_BASE_FORM, **(overrides or {})}
    resp = client.post("/quote/new", data=data, follow_redirects=False)
    assert resp.status_code == 302
    ref = unquote(resp.headers["Location"].rstrip("/").split("/quote/")[-1])
    return ref


class TestFormHasDdpFields:
    """The New Quote form must expose invoice_usd / insurance_usd inputs."""

    def test_invoice_and_insurance_inputs_exist(self):
        src = _TEMPLATE.read_text(encoding="utf-8")
        assert re.search(r'name=["\']invoice_usd["\']', src), "invoice_usd input missing"
        assert re.search(r'name=["\']insurance_usd["\']', src), "insurance_usd input missing"

    def test_visibility_toggles_on_incoterm_value(self):
        """Fields must appear for DDP and disappear for every other incoterm."""
        src = _TEMPLATE.read_text(encoding="utf-8")
        assert "incotermSel.value === 'DDP'" in src
        assert "ddpFields.style.display" in src

    def test_fields_cleared_when_switching_away_from_ddp(self):
        """display:none alone still submits stale values — must clear .value too."""
        src = _TEMPLATE.read_text(encoding="utf-8")
        fn_match = re.search(
            r"function updateDdpFieldsVisibility\s*\([^)]*\)\s*\{(.*?)\n  \}\n  if \(incotermSel\)",
            src, re.S,
        )
        assert fn_match, "updateDdpFieldsVisibility function not found"
        body = fn_match.group(1)
        assert "invoice-usd-input" in body, "must clear the invoice_usd input on switch-away"
        assert "insurance-usd-input" in body, "must clear the insurance_usd input on switch-away"
        assert re.search(r"\.value\s*=\s*['\"]['\"]", body), (
            "must actually clear .value (not just hide) so stale values can't "
            "be submitted on a non-DDP quote"
        )


class TestCreateQuoteCapturesDdpFields:
    """create_quote() must persist the submitted values, not silently drop them."""

    def test_costeo_json_stores_invoice_and_insurance(self, client):
        ref = _post_quote(client)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code = ?", (ref,)
            ).fetchone()
        import json
        costeo = json.loads(row["costeo_json"])
        assert costeo["invoice_usd"] == 50_000.00
        assert costeo["insurance_usd"] == 250.00

    def test_non_ddp_quote_stores_none(self, client):
        ref = _post_quote(client, {"incoterm": "FOB"})
        with get_connection() as conn:
            row = conn.execute(
                "SELECT costeo_json FROM quotes WHERE reference_code = ?", (ref,)
            ).fetchone()
        import json
        costeo = json.loads(row["costeo_json"])
        assert costeo["invoice_usd"] is None
        assert costeo["insurance_usd"] is None


class TestFullFormToProformaPath:
    """End-to-end: form submission -> rendered proforma duties block."""

    def test_ddp_proforma_renders_real_submitted_values(self, client, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "WEASYPRINT_AVAILABLE", False)

        ref = _post_quote(client)
        resp = client.get(f"/quote/{ref}/preview.pdf")
        html = resp.data.decode("utf-8")

        assert "56,250.00" in html   # CIF (Invoice 50,000 + Insurance 250 + Freight 6,000)
        assert "5,625.00" in html    # Advalorem
        assert "9,900.00" in html    # IGV
        assert "1,237.50" in html    # IPM
        assert "2,555.44" in html    # Percepcion
        assert "19,317.94" in html   # Subtotal B

    def test_non_ddp_quote_has_no_duties_block_end_to_end(self, client, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "WEASYPRINT_AVAILABLE", False)

        ref = _post_quote(client, {"incoterm": "FOB"})
        resp = client.get(f"/quote/{ref}/preview.pdf")
        html = resp.data.decode("utf-8")

        assert "Advalorem" not in html
        assert "Percepción" not in html
        assert "Total CIF" not in html
