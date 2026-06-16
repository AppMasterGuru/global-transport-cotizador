"""
Regression tests for PDF meta mode/incoterm (2026-06-16 verification Bug 2).

Bug: preview_pdf() and the PDF-attach path inside mark_sent() both set
meta["mode"] = costeo.get("mode", "lcl"), but the costeo JSON blob never
stores a "mode" key — so EVERY client PDF defaulted to "LCL" regardless
of the quote's real mode. Separately, neither route's SELECT fetched the
incoterm column, so meta never had "incoterm" and it always rendered
blank. LCL-mode quotes only ever looked correct by coincidence (their
real mode matched the hardcoded fallback).

The quotes table's `mode` and `incoterm` columns are NOT NULL and are
the reliable source of truth (mode has a CHECK constraint limiting it
to 'aereo'|'lcl'|'fcl') — meta must be built from those columns, not
from the costeo JSON blob.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("DB_PATH", _tmp_db.name)

from core.db import get_connection, init_db, transition_status  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    with get_connection() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS quotes;
            DROP TABLE IF EXISTS ref_counters;
            DROP TABLE IF EXISTS providers;
            DROP TABLE IF EXISTS provider_replies;
        """)
    init_db()
    yield


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


# costeo_json deliberately has NO "mode" key, matching the real shape
# written by create_quote() — proves meta can't be sourced from costeo.
_COSTEO = json.dumps({
    "flete_internacional_usd": 300.0,
    "visto_bueno_usd": 80.0,
    "handling_aereo_usd": 0.0,
    "handling_aereo_detail": {},
    "customs_agent_usd": 70.0,
    "transport_usd": 50.0,
    "transport_soles": 187.5,
    "transport_detail": {},
    "total_usd": 500.0,
    "exchange_rate": 3.75,
    "consolidator": "MSL",
    "airline": None,
    "customs_agent": "Test Agent",
})
_VENTA = json.dumps({
    "line_items": [{"description": "Flete", "quantity": 1, "unit_price": 500.0, "total": 500.0}],
    "total_usd": 600.0,
    "margin_pct": 0.20,
    "validity_days": 15,
})


def _insert_quote(ref: str, mode: str, incoterm: str, client_email: str = "client@example.com") -> int:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO quotes
              (reference_code, client_name, client_email, incoterm, mode, origin, destination,
               cargo_description, weight_kg, volume_cbm, dimensions_json,
               costeo_json, venta_json, margin_pct, exchange_rate, status, staff_code, language)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,?)
            """,
            (
                ref, "Test Client", client_email, incoterm, mode,
                "Lima, Peru", "Hamburgo, Alemania", "Uvas", 500.0, 2.0,
                json.dumps({"l": 40, "w": 30, "h": 20, "qty": 1}),
                _COSTEO, _VENTA, 0.20, 3.75, "GT-PC", "es",
            ),
        )
        conn.commit()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM quotes WHERE reference_code = ?", (ref,)).fetchone()
    quote_id = row["id"]
    transition_status(quote_id, "APPROVED", "test")
    return quote_id


def _mode_value(html: str) -> str:
    marker = '<span class="info-label">Modo</span>'
    i = html.find(marker)
    assert i != -1, "Modo field not found in rendered HTML"
    start = html.find('<span class="info-value">', i) + len('<span class="info-value">')
    end = html.find("</span>", start)
    return html[start:end].strip()


def _incoterm_value(html: str) -> str:
    marker = '<span class="info-label">Incoterm</span>'
    i = html.find(marker)
    assert i != -1, "Incoterm field not found in rendered HTML"
    start = html.find('<span class="info-value">', i) + len('<span class="info-value">')
    end = html.find("</span>", start)
    return html[start:end].strip()


class TestPreviewPdfMetaMode:
    """Forces the HTML fallback (no WeasyPrint) to inspect the exact same
    meta dict / render_html() substitution the real PDF path uses.

    Reference codes deliberately avoid embedding the mode name as a
    substring (e.g. "...-FCL-...") — an earlier draft of this test used
    refs like "26-06-MODE-FCL", and since the ref code itself is echoed
    into the rendered HTML, a bare `"FCL" in html` assertion passed even
    on the buggy code by matching the ref code, not the Modo field.
    """

    @pytest.mark.parametrize("mode,expected_label", [("fcl", "FCL"), ("aereo", "AEREO"), ("lcl", "LCL")])
    def test_renders_correct_mode(self, client, monkeypatch, mode, expected_label):
        import api.routes as routes
        monkeypatch.setattr(routes, "WEASYPRINT_AVAILABLE", False)
        ref = "26-06-PDFCHECK-001"
        _insert_quote(ref, mode=mode, incoterm="FCA")
        resp = client.get(f"/quote/{ref}/preview.pdf")
        html = resp.data.decode("utf-8")
        assert _mode_value(html) == expected_label

    def test_fcl_does_not_render_as_lcl(self, client, monkeypatch):
        """The exact original bug: an FCL quote's PDF showed 'LCL'."""
        import api.routes as routes
        monkeypatch.setattr(routes, "WEASYPRINT_AVAILABLE", False)
        _insert_quote("26-06-PDFCHECK-002", mode="fcl", incoterm="FOB")
        resp = client.get("/quote/26-06-PDFCHECK-002/preview.pdf")
        html = resp.data.decode("utf-8")
        assert _mode_value(html) == "FCL"

    @pytest.mark.parametrize("incoterm", ["FOB", "FCA", "DAP"])
    def test_renders_correct_incoterm(self, client, monkeypatch, incoterm):
        import api.routes as routes
        monkeypatch.setattr(routes, "WEASYPRINT_AVAILABLE", False)
        ref = "26-06-PDFCHECK-003"
        _insert_quote(ref, mode="lcl", incoterm=incoterm)
        resp = client.get(f"/quote/{ref}/preview.pdf")
        html = resp.data.decode("utf-8")
        assert _incoterm_value(html) == incoterm


class TestMarkSentPdfAttachmentMeta:
    """mark_sent() builds its own separate meta dict for the email
    attachment — same bug, different code location. Spy on
    generate_pdf_bytes() to inspect the meta it was actually called with,
    without needing a real WeasyPrint render."""

    def test_attachment_meta_has_correct_mode_and_incoterm(self, client, monkeypatch):
        import api.routes as routes
        captured = {}

        def _spy(venta, meta):
            captured.update(meta)
            return b"%PDF-fake"

        monkeypatch.setattr(routes, "generate_pdf_bytes", _spy)
        _insert_quote("26-06-ATTACH-001", mode="fcl", incoterm="DAP")
        client.post("/quote/26-06-ATTACH-001/send", data={"actor": "JP"}, follow_redirects=False)
        assert captured.get("mode") == "fcl"
        assert captured.get("incoterm") == "DAP"
