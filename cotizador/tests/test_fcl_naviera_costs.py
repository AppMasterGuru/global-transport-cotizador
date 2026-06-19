"""
Tests for FCL naviera-keyed cost lookups — Abel Parte 2 (2026-06-19).

Export: Visto Bueno (with desglose) + Gate Out, parsed from the
EXPORTACION-CALLAO sheet of EXPO_IMPO.xlsx (Client Data/Part 2_Abel/).
Fixtures mirror the real sheet's exact row shape (leading/trailing None
padding from merged cells) so the parser is exercised against the real
layout, not a simplified one.

Also covers the precinto recargo rule: when an export has more than one
container, the 2nd container carries a +50% surcharge of the customs
agent's commission.
"""

from __future__ import annotations

import io

import openpyxl
import pytest

from core.fcl_naviera_costs import (
    apply_second_container_surcharges,
    get_export_gate_out,
    get_export_visto_bueno,
    parse_export_naviera_sheet,
    precinto_total_usd,
    second_container_surcharge,
)


def _make_export_naviera_xlsx() -> bytes:
    """Mirrors EXPORTACION-CALLAO in EXPO_IMPO.xlsx — same row shapes,
    trimmed to the rows the parser needs (a few representative blocks)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EXPORTACION-CALLAO"

    rows = [
        [None] * 12,
        [None] * 12,
        [None, None, None, None, None, "VALIDEZ", "2026-05-30", None, None, None, None, None],
        [None] * 12,
        [None, None, None, None, None, "El siguiente formato...", None, None, None, None, None, None],
        [None] * 12,
        [None] * 12,
        [None] * 12,
        [None] * 12,
        [None, "CALLAO", "#VALUE!", None, None, None, None, None, None, None, None, None],
        [None, None, "CONCEPTO", None, None, None, "MONTO $", "IGV", "TOTAL", None, None, None],
        [None, None, "VISTO BUENO (DESPACHO DE CONTENEDOR | DESPACHO DOCUMENTARIO | REVISIÓN DE HBL)",
         None, None, None, 365, 65.7, 430.7, None, None, None],
        [None] * 12,
        [None, "DESGLOSE DEL VISTO BUENO", None, None, None, None, None, None, None, None, None, None],
        [None, "CONCEPTO", None, None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "DESPACHO DEL CONTENEDOR", None, None, None, 135, 24.3, 159.3, "CONTENEDOR", None, None, None],
        [None, "DESPACHO DOCUMENTARIO", None, None, None, 120, 21.6, 141.6, "BL", None, None, None],
        [None, "REVISIÓN DE HBL", None, None, None, 110, 19.8, 129.8, "BL", None, None, None],
        [None] * 12,
        [None, "ALMACÉN", "CONCEPTO", None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "MEDLOG", "GATE OUT | 20' &40", None, None, 152, 27.36, 179.36, "CONTENEDOR", None, None, None],
        [None] * 12,
        [None, "NOTA: ...", None, None, None, None, None, None, None, None, None, None],
        [None] * 12,
        [None, "CALLAO", None, None, None, None, None, None, None, None, None, None],
        [None, None, "CONCEPTO", None, None, None, "MONTO $", "IGV", "TOTAL", None, None, None],
        [None, None, "VISTO BUENO (METAL SECURITY SEAL | BOX FEE EXPO | ADMINISTRATIVE CHARGES | DOC FEE)",
         None, None, None, 272, 48.96, 320.96, None, None, None],
        [None] * 12,
        [None] * 12,
        [None] * 12,
        [None, "DESGLOSE DEL VISTO BUENO", None, None, None, None, None, None, None, None, None, None],
        [None, "CONCEPTO", None, None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "METAL SECURITY SEAL", None, None, None, 17, 3.06, 20.06, "CONTENEDOR", None, None, None],
        [None, "BOX FEE EXPO", None, None, None, 130, 23.4, 153.4, "CONTENEDOR", None, None, None],
        [None, "ADMINISTRATIVE CHARGES", None, None, None, 10, 1.8, 11.8, "BL", None, None, None],
        [None, "DOC FEE", None, None, None, 115, 20.7, 135.7, "BL", None, None, None],
        [None] * 12,
        [None, "ALMACÉN", "CONCEPTO", None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "CONTRANS", "GATE OUT | 20' & 40'", None, None, 150, 27, 177, "CONTENEDOR", None, None, None],
        [None, "DPW", "GATE OUT | 20' & 40'", None, None, 150, 27, 177, None, None, None, None],
        [None] * 12,
        [None] * 12,
        [None, "CALLAO", "#VALUE!", None, None, None, None, None, None, None, None, None],
        [None, None, "CONCEPTO", None, None, None, "MONTO $", "RETENCIÓN", "TOTAL", None, None, None],
        [None, None, "VISTO BUENO (BOX FEE | COVERAGE FEE)", None, None, None, 112, 48, 160, None, None, None],
        [None] * 12,
        [None] * 12,
        [None, "DESGLOSE DEL VISTO BUENO", None, None, None, None, None, None, None, None, None, None],
        [None, "CONCEPTO", None, None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "BOX FEE - EXPO MSK", None, None, None, 80.5, 34.5, 115, "CONTENEDOR", None, None, None],
        [None, "COVERAGE FEE - EXPO MSK", None, None, None, 31.5, 13.5, 45, "CONTENEDOR", None, None, None],
        [None] * 12,
        [None, "ALMACÉN", "CONCEPTO", None, None, "MONTO $", "IGV", "TOTAL", "TIPO", None, None, None],
        [None, "DEMARES", "GATE OUT | 20' & 40'", None, None, 179, 32.22, 211.22, "CONTENEDOR", None, None, None],
    ]
    for r in rows:
        ws.append(r)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def parsed():
    wb = openpyxl.load_workbook(io.BytesIO(_make_export_naviera_xlsx()), data_only=True, read_only=True)
    ws = wb["EXPORTACION-CALLAO"]
    return parse_export_naviera_sheet(ws)


class TestGateOut:
    def test_medlog(self, parsed):
        g = get_export_gate_out(parsed, "MEDLOG")
        assert g["net"] == pytest.approx(152.0, rel=0.001)
        assert g["total"] == pytest.approx(179.36, rel=0.001)

    def test_contrans(self, parsed):
        g = get_export_gate_out(parsed, "CONTRANS")
        assert g["net"] == pytest.approx(150.0, rel=0.001)
        assert g["total"] == pytest.approx(177.0, rel=0.001)

    def test_dpw(self, parsed):
        g = get_export_gate_out(parsed, "DPW")
        assert g["net"] == pytest.approx(150.0, rel=0.001)
        assert g["total"] == pytest.approx(177.0, rel=0.001)

    def test_demares(self, parsed):
        g = get_export_gate_out(parsed, "DEMARES")
        assert g["net"] == pytest.approx(179.0, rel=0.001)
        assert g["total"] == pytest.approx(211.22, rel=0.001)

    def test_unknown_returns_none(self, parsed):
        assert get_export_gate_out(parsed, "NOT-A-REAL-DEPOT") is None

    def test_case_insensitive(self, parsed):
        g = get_export_gate_out(parsed, "medlog")
        assert g["total"] == pytest.approx(179.36, rel=0.001)


class TestVistoBuenoMaersk:
    def test_maersk_identified_via_msk_token(self, parsed):
        vb = get_export_visto_bueno(parsed, "MAERSK")
        assert vb is not None

    def test_maersk_total_is_160_retencion_model(self, parsed):
        vb = get_export_visto_bueno(parsed, "MAERSK")
        assert vb["total"] == pytest.approx(160.0, rel=0.001)

    def test_maersk_desglose_has_box_fee_80_5(self, parsed):
        vb = get_export_visto_bueno(parsed, "MAERSK")
        box_fee = next(d for d in vb["desglose"] if "BOX FEE" in d["concept"])
        assert box_fee["monto"] == pytest.approx(80.5, rel=0.001)

    def test_maersk_desglose_has_coverage_fee_31_5(self, parsed):
        vb = get_export_visto_bueno(parsed, "MAERSK")
        coverage = next(d for d in vb["desglose"] if "COVERAGE FEE" in d["concept"])
        assert coverage["monto"] == pytest.approx(31.5, rel=0.001)

    def test_unidentified_naviera_returns_none(self, parsed):
        # First VB block (Despacho/Documentario/HBL) has no identifiable
        # naviera token — must not be silently mis-attributed to anything.
        assert get_export_visto_bueno(parsed, "CMA CGM") is None


class TestSecondContainerSurcharge:
    """Abel: 'si son más de 1 contenedor se aplica un recargo del 50% del
    costo de la comisión del agente de aduanas al segundo contendor.'"""

    def test_single_container_no_surcharge(self):
        assert second_container_surcharge(100.0, container_index=1) == 0.0

    def test_second_container_50pct_surcharge(self):
        assert second_container_surcharge(100.0, container_index=2) == pytest.approx(50.0, rel=0.001)

    def test_one_container_list_no_surcharge(self):
        surcharges = apply_second_container_surcharges(100.0, num_containers=1)
        assert surcharges == [0.0]

    def test_two_containers_list_second_carries_surcharge(self):
        surcharges = apply_second_container_surcharges(100.0, num_containers=2)
        assert surcharges == [0.0, pytest.approx(50.0, rel=0.001)]


class TestPrecintoQ8:
    """Abel Parte 2 Q8 (2026-06-19): Alefero standard precinto is USD 10.00
    + IGV per container, flat (Abel: 'por contenedor') — NOT subject to
    the 2nd-container +50% surcharge that applies to the customs agent
    commission."""

    def test_one_container_is_10(self):
        assert precinto_total_usd(num_containers=1) == pytest.approx(10.0, rel=0.001)

    def test_two_containers_is_flat_20_not_surcharged(self):
        assert precinto_total_usd(num_containers=2) == pytest.approx(20.0, rel=0.001)

    def test_three_containers_is_flat_30(self):
        assert precinto_total_usd(num_containers=3) == pytest.approx(30.0, rel=0.001)
