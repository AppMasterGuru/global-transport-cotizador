"""
Tests for FCL import local costs by naviera — Abel Parte 2 (2026-06-19).

Abel's explicit written rule: FCL import charges are THC + ISPS + MBL
emission ONLY. Parsed (not hardcoded) from:
  - G. LOCALES sheet -> THCD (20'/40') + ISPS/adicional (20'/40')
  - EMISION MBL sheet -> MBL emission cost per naviera

HOLD (TODO abel-Q3): there is a second import structure (EXPO_IMPO
IMPORTACIÓN sheet's VB IMPORTACION layer) that may stack with or replace
the above — explicitly NOT wired into the import total this session.
"""

from __future__ import annotations

import io

import openpyxl
import pytest

from core.fcl_import_costs import (
    get_fcl_import_local_costs,
    parse_g_locales_sheet,
    parse_mbl_sheet,
)


def _make_g_locales_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "G. LOCALES"
    rows = [
        ["NAVIERA", "AGENTE \nMARITIMO", "POD", "THCD", None, "ADICIONALES", None, None],
        [None, None, None, "20'", "40'", "CONCEPTO", "20'", "40'"],
        ["CMA CGM / APL", "IAN TAYLOR", "Callao", 65, 70, "ISPS", 14, 14],
        [None, None, None, 40, 65, None, None, None],
        ["COSCO / OOCL", "COSCO PERU", "Callao", 55, 55, "ISPS", 6, 6],
        ["MAERSK / SEALAND", "COLUMBUS", "Callao", 110, 110, "DOC FEE", 55, 55],
        ["MSC", "MSC PERU", "Callao", 65, 65, None, None, None],
        ["SEABOARD", "CITIKOLD", "Callao", "NO COBRA", "NO COBRA", None, None, None],
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_mbl_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EMISION MBL"
    rows = [
        ["NAVIERA", "COSTO POR EMISION MBL", "SEA WAYBILL / TELEX"],
        ["APL", "USD 55.00 + IGV", "NO"],
        ["CMA CGM", "USD 55.00 + IGV", "SI", None, "VB FCL VÍA GT"],
        ["COSCO / OOCL", "USD 30.00 + IGV", "SI"],
        ["MAERSK / SEALAND", "DOC FEE USD 55.00", "SI"],
        ["MSC", "USD 57.00 + IGV", "NO"],
        ["SEABOARD", "USD 35.00 + IGV", "NO"],
        ["ONE", "USD 29,50 + IGV", "SI"],
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def g_locales():
    wb = openpyxl.load_workbook(io.BytesIO(_make_g_locales_xlsx()), data_only=True, read_only=True)
    return parse_g_locales_sheet(wb["G. LOCALES"])


@pytest.fixture
def mbl():
    wb = openpyxl.load_workbook(io.BytesIO(_make_mbl_xlsx()), data_only=True, read_only=True)
    return parse_mbl_sheet(wb["EMISION MBL"])


class TestGLocalesParsing:
    def test_cma_apl_thc(self, g_locales):
        e = g_locales["CMA CGM / APL"]
        assert e["thc_20"] == pytest.approx(65.0, rel=0.001)
        assert e["thc_40"] == pytest.approx(70.0, rel=0.001)

    def test_cma_apl_isps(self, g_locales):
        e = g_locales["CMA CGM / APL"]
        assert e["adicional_concept"] == "ISPS"
        assert e["adicional_20"] == pytest.approx(14.0, rel=0.001)
        assert e["adicional_40"] == pytest.approx(14.0, rel=0.001)

    def test_cosco_oocl(self, g_locales):
        e = g_locales["COSCO / OOCL"]
        assert e["thc_20"] == pytest.approx(55.0, rel=0.001)
        assert e["thc_40"] == pytest.approx(55.0, rel=0.001)
        assert e["adicional_20"] == pytest.approx(6.0, rel=0.001)
        assert e["adicional_40"] == pytest.approx(6.0, rel=0.001)

    def test_maersk_sealand_doc_fee(self, g_locales):
        e = g_locales["MAERSK / SEALAND"]
        assert e["thc_20"] == pytest.approx(110.0, rel=0.001)
        assert e["thc_40"] == pytest.approx(110.0, rel=0.001)
        assert e["adicional_concept"] == "DOC FEE"
        assert e["adicional_20"] == pytest.approx(55.0, rel=0.001)
        assert e["adicional_40"] == pytest.approx(55.0, rel=0.001)

    def test_seaboard_no_cobra(self, g_locales):
        e = g_locales["SEABOARD"]
        assert e["thc_20"] is None
        assert e["thc_40"] is None
        assert e["no_cobra"] is True


class TestMblParsing:
    def test_apl_55_plus_igv(self, mbl):
        e = mbl["APL"]
        assert e["amount"] == pytest.approx(55.0, rel=0.001)
        assert e["currency"] == "USD"
        assert e["plus_igv"] is True

    def test_cosco_oocl_30_plus_igv(self, mbl):
        e = mbl["COSCO / OOCL"]
        assert e["amount"] == pytest.approx(30.0, rel=0.001)
        assert e["currency"] == "USD"

    def test_maersk_sealand_doc_fee_55(self, mbl):
        e = mbl["MAERSK / SEALAND"]
        assert e["amount"] == pytest.approx(55.0, rel=0.001)
        assert "DOC FEE" in e["raw"]

    def test_comma_decimal_parsed(self, mbl):
        # "USD 29,50 + IGV" -> 29.50, not 2950
        e = mbl["ONE"]
        assert e["amount"] == pytest.approx(29.50, rel=0.001)


class TestFclImportLocalCostsCombined:
    """Abel's rule: THC + ISPS + MBL only."""

    def test_cma_apl_combined(self, g_locales, mbl):
        c = get_fcl_import_local_costs(g_locales, mbl, "CMA CGM / APL")
        assert c["thc_20"] == pytest.approx(65.0, rel=0.001)
        assert c["isps_20"] == pytest.approx(14.0, rel=0.001)
        assert c["mbl_usd"] == pytest.approx(55.0, rel=0.001)

    def test_cosco_oocl_combined(self, g_locales, mbl):
        c = get_fcl_import_local_costs(g_locales, mbl, "COSCO / OOCL")
        assert c["thc_20"] == pytest.approx(55.0, rel=0.001)
        assert c["isps_20"] == pytest.approx(6.0, rel=0.001)
        assert c["mbl_usd"] == pytest.approx(30.0, rel=0.001)

    def test_maersk_sealand_combined(self, g_locales, mbl):
        c = get_fcl_import_local_costs(g_locales, mbl, "MAERSK / SEALAND")
        assert c["thc_20"] == pytest.approx(110.0, rel=0.001)
        assert c["mbl_usd"] == pytest.approx(55.0, rel=0.001)

    def test_seaboard_no_cobra_handled_cleanly(self, g_locales, mbl):
        c = get_fcl_import_local_costs(g_locales, mbl, "SEABOARD")
        assert c["thc_20"] is None
        assert c["thc_no_cobra"] is True
        assert c["mbl_usd"] == pytest.approx(35.0, rel=0.001)

    def test_unknown_naviera_returns_none(self, g_locales, mbl):
        assert get_fcl_import_local_costs(g_locales, mbl, "NOT-A-REAL-LINE") is None
