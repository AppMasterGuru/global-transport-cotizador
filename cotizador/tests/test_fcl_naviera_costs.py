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
    export_naviera_options,
    fcl_customs_agent_costs,
    fcl_oea_basc_commission_per_container_usd,
    fcl_oea_basc_commission_total_usd,
    fcl_oea_basc_gastos_operativos_usd,
    fcl_oea_basc_precinto_total_usd,
    get_export_gate_out,
    get_export_gate_outs,
    get_export_vb_net_usd,
    get_export_visto_bueno,
    parse_export_naviera_sheet,
    precinto_total_usd,
    resolve_export_gate_out,
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


class TestFclOeaBascTieredCustomsAgentQ6:
    """Abel Parte 2 Q6 (FCL export): the OEA+BASC certified customs agent's
    commission is tiered by container count — 1 cntr USD 70, 2 cntrs USD
    50/cntr, 3+ cntrs USD 40/cntr — plus flat gastos operativos USD 20 and
    precinto USD 5/cntr (this agent's own precinto rate, separate from
    Alefero's USD 10/cntr)."""

    def test_one_container_rate_is_70(self):
        assert fcl_oea_basc_commission_per_container_usd(1) == pytest.approx(70.0, rel=0.001)

    def test_two_container_rate_is_50(self):
        assert fcl_oea_basc_commission_per_container_usd(2) == pytest.approx(50.0, rel=0.001)

    def test_three_container_rate_is_40(self):
        assert fcl_oea_basc_commission_per_container_usd(3) == pytest.approx(40.0, rel=0.001)

    def test_four_container_rate_still_40(self):
        assert fcl_oea_basc_commission_per_container_usd(4) == pytest.approx(40.0, rel=0.001)

    def test_one_container_total_is_70(self):
        assert fcl_oea_basc_commission_total_usd(1) == pytest.approx(70.0, rel=0.001)

    def test_two_containers_total_is_100(self):
        assert fcl_oea_basc_commission_total_usd(2) == pytest.approx(100.0, rel=0.001)

    def test_three_containers_total_is_120(self):
        assert fcl_oea_basc_commission_total_usd(3) == pytest.approx(120.0, rel=0.001)

    def test_five_containers_total_is_200(self):
        assert fcl_oea_basc_commission_total_usd(5) == pytest.approx(200.0, rel=0.001)

    def test_gastos_operativos_is_flat_20_regardless_of_container_count(self):
        assert fcl_oea_basc_gastos_operativos_usd() == pytest.approx(20.0, rel=0.001)

    def test_precinto_one_container_is_5(self):
        assert fcl_oea_basc_precinto_total_usd(1) == pytest.approx(5.0, rel=0.001)

    def test_precinto_two_containers_is_flat_10(self):
        assert fcl_oea_basc_precinto_total_usd(2) == pytest.approx(10.0, rel=0.001)

    def test_precinto_three_containers_is_flat_15(self):
        assert fcl_oea_basc_precinto_total_usd(3) == pytest.approx(15.0, rel=0.001)


class TestExportNavieraData:
    """Export VB table — Abel June 22 confirmed 7-naviera mapping (Q2 resolution).
    Source: EXPORTACION-CALLAO sheet of EXPO_IMPO.xlsx, naviera-keyed."""

    def test_all_seven_navieras_present(self):
        for nav in ["MSC", "ONE", "MAERSK", "HAPAG LLOYD", "CMA CGM", "COSCO", "EVERGREEN"]:
            assert get_export_vb_net_usd(nav) is not None, f"{nav} missing from export VB table"

    def test_msc_vb_net_usd(self):
        assert get_export_vb_net_usd("MSC") == pytest.approx(365.0, rel=0.001)

    def test_one_vb_net_usd(self):
        assert get_export_vb_net_usd("ONE") == pytest.approx(272.0, rel=0.001)

    def test_maersk_vb_is_160_retencion_case(self):
        # MAERSK: retención 30% (not IGV). Base monto=$112, total=$160.
        # Stored as $160 pending retención handling — TODO(abel-F1F4).
        assert get_export_vb_net_usd("MAERSK") == pytest.approx(160.0, rel=0.001)

    def test_maersk_via_slash_form_name(self):
        # Dropdown sends "MAERSK / SEALAND" — slash-stripping inside the function.
        assert get_export_vb_net_usd("MAERSK / SEALAND") == pytest.approx(160.0, rel=0.001)

    def test_hapag_lloyd_vb_net_usd(self):
        assert get_export_vb_net_usd("HAPAG LLOYD") == pytest.approx(152.0, rel=0.001)

    def test_cma_cgm_vb_net_usd(self):
        # Net pre-IGV: 219.35 × 1.18 = 258.83 (resolves previous double-IGV bug).
        assert get_export_vb_net_usd("CMA CGM") == pytest.approx(219.35, rel=0.001)

    def test_cma_cgm_via_slash_form_name(self):
        # Dropdown sends "CMA CGM / APL"
        assert get_export_vb_net_usd("CMA CGM / APL") == pytest.approx(219.35, rel=0.001)

    def test_cosco_vb_net_usd(self):
        assert get_export_vb_net_usd("COSCO") == pytest.approx(100.0, rel=0.001)

    def test_cosco_via_slash_form_name(self):
        # Dropdown sends "COSCO / OOCL"
        assert get_export_vb_net_usd("COSCO / OOCL") == pytest.approx(100.0, rel=0.001)

    def test_evergreen_vb_net_usd(self):
        assert get_export_vb_net_usd("EVERGREEN") == pytest.approx(227.0, rel=0.001)

    def test_unknown_naviera_returns_none(self):
        assert get_export_vb_net_usd("UNKNOWN CARRIER") is None

    def test_case_insensitive(self):
        assert get_export_vb_net_usd("msc") == pytest.approx(365.0, rel=0.001)

    def test_medlog_gate_out_for_msc(self):
        gates = get_export_gate_outs("MSC")
        assert gates["MEDLOG"]["net"] == pytest.approx(152.0, rel=0.001)
        assert gates["MEDLOG"]["total"] == pytest.approx(179.36, rel=0.001)

    def test_demares_gate_out_for_maersk(self):
        gates = get_export_gate_outs("MAERSK")
        assert gates["DEMARES"]["net"] == pytest.approx(179.0, rel=0.001)
        assert gates["DEMARES"]["total"] == pytest.approx(211.22, rel=0.001)

    def test_imupesa_gate_out_for_cma_cgm(self):
        gates = get_export_gate_outs("CMA CGM")
        assert gates["IMUPESA"]["net"] == pytest.approx(150.0, rel=0.001)

    def test_three_gate_out_depots_for_evergreen(self):
        gates = get_export_gate_outs("EVERGREEN")
        assert set(gates) == {"TPP", "IMUPESA", "DP WORLD LOGISTICS"}

    def test_imupesa_gate_out_for_evergreen_is_133_50(self):
        # IMUPESA appears in both CMA CGM block ($150) and EVERGREEN block ($133.50).
        # Naviera-keyed table resolves this conflict; each naviera gets its own value.
        gates = get_export_gate_outs("EVERGREEN")
        assert gates["IMUPESA"]["net"] == pytest.approx(133.5, rel=0.001)

    def test_gate_outs_empty_for_unknown_naviera(self):
        assert get_export_gate_outs("UNKNOWN") == {}


class TestResolveExportGateOut:
    """resolve_export_gate_out() collapses a naviera's (possibly multi-depot)
    export Gate Out into ONE figure for the agente EXW quote. There is no
    depot-selection mechanism in the cotizador (cliente_local has never charged
    export Gate Out — it only charges VB), so it picks the no-overcharge
    (minimum-net) depot deterministically and records which one, for Abel F4."""

    def test_single_depot_navieras(self):
        # Navieras with one depot resolve to that depot unambiguously.
        for naviera, depot, net in [
            ("MSC", "MEDLOG", 152.0),
            ("MAERSK", "DEMARES", 179.0),
            ("HAPAG LLOYD", "RANSA", 150.0),
            ("CMA CGM", "IMUPESA", 150.0),
            ("COSCO", "FARGOLINE", 125.5),
        ]:
            g = resolve_export_gate_out(naviera)
            assert g["depot"] == depot, naviera
            assert g["net"] == pytest.approx(net, rel=0.001), naviera

    def test_one_ties_resolve_to_alphabetical_min(self):
        # ONE: CONTRANS 150 vs DPW 150 — equal net, deterministic tie-break
        # (alphabetical) → CONTRANS.
        g = resolve_export_gate_out("ONE")
        assert g["net"] == pytest.approx(150.0, rel=0.001)
        assert g["depot"] == "CONTRANS"

    def test_evergreen_picks_lowest_net_no_overcharge(self):
        # EVERGREEN: TPP 120.5 / IMUPESA 133.5 / DP WORLD LOGISTICS 120.5.
        # No-overcharge default = minimum net (120.5); tie broken alphabetically
        # → "DP WORLD LOGISTICS" (before "TPP").
        g = resolve_export_gate_out("EVERGREEN")
        assert g["net"] == pytest.approx(120.5, rel=0.001)
        assert g["depot"] == "DP WORLD LOGISTICS"

    def test_carries_igv_and_total_fields(self):
        g = resolve_export_gate_out("MSC")
        assert g["igv"] == pytest.approx(27.36, rel=0.001)
        assert g["total"] == pytest.approx(179.36, rel=0.001)

    def test_unknown_naviera_returns_none(self):
        assert resolve_export_gate_out("UNKNOWN CARRIER") is None

    def test_case_insensitive(self):
        assert resolve_export_gate_out("cosco")["depot"] == "FARGOLINE"


class TestExportNavieraOptions:
    """The agente EXW Naviera dropdown must offer EXACTLY the navieras that have
    an export VB table entry — no more (an off-list naviera has no VB/gate to
    resolve) and no less (Abel's carrier must be selectable)."""

    def test_exactly_the_seven_export_navieras(self):
        assert export_naviera_options() == sorted([
            "MSC", "ONE", "MAERSK", "HAPAG LLOYD", "CMA CGM", "COSCO", "EVERGREEN",
        ])

    def test_every_option_resolves_a_vb_and_gate_out(self):
        for n in export_naviera_options():
            assert get_export_vb_net_usd(n) is not None, n
            assert resolve_export_gate_out(n) is not None, n

    def test_maersk_included_despite_retencion_todo(self):
        # MAERSK's $160 is retención-inclusive (open TODO abel-F1F4) — it must
        # still be selectable; the retención treatment is a separate pass.
        assert "MAERSK" in export_naviera_options()


class TestFclCustomsAgentCostsDispatch:
    """FCL-specific customs agent dispatch (Session E) — supersedes the
    generic transport.get_customs_agent() path for mode='fcl', which knows
    nothing about the 2nd-container surcharge or OEA+BASC per-container
    tiering."""

    def test_alefero_one_container(self):
        c = fcl_customs_agent_costs(requires_oea_basc=False, num_containers=1)
        assert c["agent_name"] == "Alefero"
        assert c["commission_usd"] == pytest.approx(50.0, rel=0.001)
        assert c["gastos_operativos_usd"] == pytest.approx(0.0, rel=0.001)
        assert c["precinto_usd"] == pytest.approx(10.0, rel=0.001)

    def test_alefero_two_containers_commission_includes_surcharge(self):
        # Base 50 + 2nd-container 50% surcharge (25) = 75.
        c = fcl_customs_agent_costs(requires_oea_basc=False, num_containers=2)
        assert c["commission_usd"] == pytest.approx(75.0, rel=0.001)
        assert c["precinto_usd"] == pytest.approx(20.0, rel=0.001)

    def test_oea_basc_one_container(self):
        c = fcl_customs_agent_costs(requires_oea_basc=True, num_containers=1)
        assert c["agent_name"] == "OEA+BASC Certified Agent"
        assert c["commission_usd"] == pytest.approx(70.0, rel=0.001)
        assert c["gastos_operativos_usd"] == pytest.approx(20.0, rel=0.001)
        assert c["precinto_usd"] == pytest.approx(5.0, rel=0.001)

    def test_oea_basc_two_containers_tiered(self):
        c = fcl_customs_agent_costs(requires_oea_basc=True, num_containers=2)
        assert c["commission_usd"] == pytest.approx(100.0, rel=0.001)
        assert c["precinto_usd"] == pytest.approx(10.0, rel=0.001)
