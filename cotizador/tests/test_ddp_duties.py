"""
DDP (Delivered Duty Paid) duties & taxes proforma block.

Formulas confirmed by Abel 2026-06-18 (verified against his Excel formula
bar — no spreadsheet artifact; the formula and his cell agree):

  CIF         = Invoice + Insurance + Freight
  Advalorem   = ADVALOREM_PCT  x CIF
  IGV         = IGV_PCT        x (CIF + Advalorem)
  IPM         = IPM_PCT        x (CIF + Advalorem)
  Percepcion  = PERCEPCION_PCT x (CIF + Advalorem + IGV + IPM)

Worked example (Abel): Invoice 50,000 + Insurance 250 + Freight 6,000 = CIF 56,250
  Advalorem  = 5,625.00
  IGV        = 9,900.00
  IPM        = 1,237.50
  Percepcion = 2,555.44
  Subtotal B = 19,317.94

CLIENT-FACING OUTPUT ONLY — these tests must never touch core/transport.py,
api/routes.py costing logic, margin, visto bueno, or customs-agent code.
"""

import pytest

from core.pdf_generator import (
    ADVALOREM_PCT,
    IGV_PCT,
    IPM_PCT,
    PERCEPCION_PCT,
    compute_ddp_duties,
    generate_html_preview,
)

ABEL_INVOICE   = 50_000.0
ABEL_INSURANCE = 250.0
ABEL_FREIGHT   = 6_000.0

_VENTA_BASE = {
    "line_items": [
        {"description": "Flete Internacional", "quantity": 1,
         "unit_price": 6000.00, "total": 6000.00, "is_local": False},
        {"description": "Visto Bueno", "quantity": 1,
         "unit_price": 160.00, "total": 160.00, "is_local": True},
    ],
    "total_usd": 0,
    "margin_pct": 0.20,
    "validity_days": 15,
}


def _meta(incoterm, lang="es", **extra):
    base = {
        "reference":     "26-06-DDP-TEST",
        "client_name":   "DDP Test SA",
        "origin":        "Shanghai, China",
        "destination":   "Callao, Peru",
        "incoterm":      incoterm,
        "mode":          "FCL",
        "staff_code":    "GT-PC",
        "language":      lang,
        "exchange_rate": 3.7,
        "weight_kg":     1000,
        "volume_cbm":    10,
    }
    base.update(extra)
    return base


class TestDdpDutiesFormula:
    """Pure formula tests against Abel's worked example."""

    @pytest.fixture
    def duties(self):
        return compute_ddp_duties(ABEL_INVOICE, ABEL_INSURANCE, ABEL_FREIGHT)

    def test_cif_total(self, duties):
        assert duties["cif_usd"] == 56_250.00

    def test_advalorem(self, duties):
        assert duties["advalorem_usd"] == 5_625.00

    def test_igv(self, duties):
        assert duties["igv_usd"] == 9_900.00

    def test_ipm(self, duties):
        assert duties["ipm_usd"] == 1_237.50

    def test_percepcion(self, duties):
        assert duties["percepcion_usd"] == 2_555.44

    def test_subtotal_b(self, duties):
        assert duties["subtotal_b_usd"] == 19_317.94


class TestRatesAreConfigurableConstants:
    def test_constants_match_abel_confirmed_rates(self):
        assert ADVALOREM_PCT == 0.10
        assert IGV_PCT == 0.16
        assert IPM_PCT == 0.02
        assert PERCEPCION_PCT == 0.035

    def test_formula_uses_constants_not_literals(self, monkeypatch):
        """Changing a constant must change the output — proves no hardcoded literal."""
        import core.pdf_generator as pg
        monkeypatch.setattr(pg, "ADVALOREM_PCT", 0.20)
        d = pg.compute_ddp_duties(ABEL_INVOICE, ABEL_INSURANCE, ABEL_FREIGHT)
        assert d["advalorem_usd"] == pytest.approx(11_250.00, abs=0.01)


class TestDdpRenderedProforma:
    """Assert against the RENDERED proforma HTML, not an internal dict."""

    @pytest.mark.parametrize("lang", ["es", "en"])
    def test_ddp_section_c_values_in_rendered_html(self, lang):
        meta = _meta(
            "DDP", lang=lang,
            invoice_usd=ABEL_INVOICE, insurance_usd=ABEL_INSURANCE, freight_usd=ABEL_FREIGHT,
        )
        html = generate_html_preview(_VENTA_BASE, meta)
        assert "5,625.00" in html       # Advalorem
        assert "9,900.00" in html       # IGV
        assert "1,237.50" in html       # IPM
        assert "2,555.44" in html       # Percepcion
        assert "19,317.94" in html      # Subtotal B
        assert "56,250.00" in html      # CIF total

    def test_ddp_total_includes_duties_subtotal(self):
        meta = _meta(
            "DDP",
            invoice_usd=ABEL_INVOICE, insurance_usd=ABEL_INSURANCE, freight_usd=ABEL_FREIGHT,
        )
        html = generate_html_preview(_VENTA_BASE, meta)
        # Subtotal A (GT service charges) = 6000 (flete) + 160*1.18 (VB+IGV) = 6,188.80
        # TOTAL = Subtotal A + Subtotal B = 6,188.80 + 19,317.94 = 25,506.74
        assert "6,188.80" in html
        assert "25,506.74" in html


class TestNonDdpNoDutiesBlock:
    """Regression: every non-DDP incoterm must render with NO duties block."""

    @pytest.mark.parametrize("incoterm", ["FOB", "CIF", "EXW", "FCA", "DAP"])
    def test_no_duties_terms_for_non_ddp(self, incoterm):
        meta = _meta(incoterm)
        html = generate_html_preview(_VENTA_BASE, meta)
        assert "Advalorem" not in html
        assert "Percepción" not in html
        assert "Perception" not in html
        assert "IPM (" not in html      # plain "IPM" also matches "SHIPMENT INFO"
        assert "Total CIF" not in html

    def test_non_ddp_total_unchanged(self):
        meta = _meta("FOB")
        html = generate_html_preview(_VENTA_BASE, meta)
        # Unaffected by duties: grand_total = 6000 + 160*1.18 = 6,188.80
        assert "6,188.80" in html
        assert "25,506.74" not in html
