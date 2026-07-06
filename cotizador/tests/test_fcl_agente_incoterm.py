"""
Tests for the FCL Agente Internacional per-incoterm concept layer.

Session L update — naviera/port-dependent amounts are now RESOLVED at runtime
from the same port_costs + naviera docs the cliente_local import path uses,
not hardcoded from the tariff sheet (Abel's reframe: the sheet is structure
only). Concepts re-sourced: Terminal Fee (port_costs), THC/ISPS (naviera
import), BL Master / MBL (naviera MBL), Visto Bueno Importación (naviera VB).
GT's own fixed service fees (Operative Charge, Agency Fee, Coordinación, Seal,
the export Customs Broker base) keep their fixed values.

Two concepts have NO clean doc source and were left at their sheet value and
flagged (do not re-source, do not guess):
  - EXW "Gate out" (export gate is per-depot, multi-valued, not wired).
  - DAP "Gate in" (no import-gate doc source exists in the system).

DDP is now wired (§2/§3/§4): THC/ISPS/MBL/VB-import/Terminal resolved from the
existing import figures, plus Operative Charge (venta) and a calculated
Customs Broker (% of CIF). Gate in is COST-only and never a venta concept.

IGV reversal (§4): Visto Bueno concepts and MBL are afecto a IGV (local);
THC and ISPS stay exempt (international). Applies across all four incoterms.

Covers:
  - Registry completeness and structure (four incoterms wired, incl. DDP)
  - RESOLVED unit: amount injected at runtime; omitted when unavailable
  - build_agente_venta_items() for EXW, FOB, DAP, DDP
  - IGV/INTL flag assertions per §4
  - Collect item renders but contributes 0 total (EXW ocean freight)
  - PER_CNTR_EXTRA skipped when num_containers == 1
  - DYNAMIC item omitted when open_transport_usd == 0
  - F1-F6 fix assertions on new incoterm outputs
"""

from __future__ import annotations

import pytest

from core.fcl_agente_incoterm import (
    DYNAMIC,
    PER_BL,
    PER_CNTR,
    PER_CNTR_EXTRA,
    RESOLVED,
    FclConcept,
    build_agente_venta_items,
    get_incoterm_concepts,
    registered_incoterms,
)


# ── Registry structure ────────────────────────────────────────────────────────

class TestRegistry:
    def test_four_incoterms_registered(self):
        keys = registered_incoterms()
        assert ("EXPO", "EXW") in keys
        assert ("EXPO", "FOB") in keys
        assert ("IMPO", "DAP") in keys
        assert ("IMPO", "DDP") in keys

    def test_ddp_now_registered(self):
        assert get_incoterm_concepts("IMPO", "DDP") is not None

    def test_unknown_incoterm_returns_none(self):
        assert get_incoterm_concepts("EXPO", "CIF") is None
        assert get_incoterm_concepts("IMPO", "FOB") is None

    def test_lookup_case_insensitive(self):
        assert get_incoterm_concepts("expo", "exw") is not None
        assert get_incoterm_concepts("Impo", "Ddp") is not None

    def test_concepts_are_fcl_concept_instances(self):
        for flujo, inc in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, inc)
            assert all(isinstance(c, FclConcept) for c in concepts)

    def test_all_concepts_have_description(self):
        for flujo, inc in registered_incoterms():
            for c in get_incoterm_concepts(flujo, inc):
                assert c.description and isinstance(c.description, str)


# ── Per-incoterm structure == Excel TARIFA NETA ──────────────────────────────
# Each registry entry's ordered concept set must equal the client-facing
# TARIFA NETA block (right-hand table) of its FCL tab in the 2025 tarifarios.
# Abel F3/F4 2026-07-06: "el incoterm determina la estructura de costos" —
# the incoterm's Excel tab is authoritative for WHICH concepts appear.
#
#   EXPO FOB tab  → Ocean Freight ONLY (Handling/Doc Fee sit in a separate
#                   "cobrados al exportador" table, not the net tariff).
#   EXPO EXW tab  → full export set (10 concepts).
#   IMPO DAP tab  → import set (8 concepts).
#   IMPO DDP tab  → import set; Box Fee/SCAC/Doc Fee/Seal/Gate-in are folded
#                   into the RESOLVED "Visto Bueno (Importación)" naviera
#                   bundle (Session L no-double-count; Gate in is COST-only).

_TARIFA_NETA_STRUCTURE = {
    ("EXPO", "FOB"): (
        "Flete Internacional (COLLECT)",
    ),
    ("EXPO", "EXW"): (
        "Flete Internacional (COLLECT)",
        "Customs Broker",
        "Customs Broker — Contenedor Adicional",
        "Operative Charge",
        "Seal",
        "Coordinación y Supervisión del Embarque",
        "Agency Fee",
        "Gate out",
        "Terminal Fee",
        "Pick up",
    ),
    ("IMPO", "DAP"): (
        "THC",
        "ISPS",
        "BL Master",
        "Coordinación y Supervisión del Embarque",
        "Agency Fee",
        "Gate in",
        "Terminal Fee",
        "Delivery",
    ),
    ("IMPO", "DDP"): (
        "THC",
        "ISPS",
        "Emisión MBL",
        "Visto Bueno (Importación)",
        "Terminal Fee",
        "Operative Charge",
        "Customs Broker",
        "Delivery",
    ),
}


class TestPerIncotermStructureMatchesExcel:
    @pytest.mark.parametrize("key,expected", list(_TARIFA_NETA_STRUCTURE.items()))
    def test_emitted_concept_set_equals_excel(self, key, expected):
        flujo, inc = key
        concepts = get_incoterm_concepts(flujo, inc)
        emitted = tuple(c.description for c in concepts)
        assert emitted == expected, (
            f"{flujo} {inc}: registry structure diverged from the Excel "
            f"TARIFA NETA. Got {emitted}, expected {expected}"
        )

    def test_fob_is_ocean_freight_only(self):
        # Explicit FOB pin (Abel F3/F4 priority): only Flete Internacional is
        # emitted — Handling, Doc Fee, THC, Terminal Fee, Transporte and Agente
        # de Aduana must all be absent from the client-facing FOB structure.
        concepts = get_incoterm_concepts("EXPO", "FOB")
        descs = {c.description for c in concepts}
        assert descs == {"Flete Internacional (COLLECT)"}
        for forbidden in ("Handling", "Doc Fee / Por BL", "THC", "ISPS",
                          "Terminal Fee", "Delivery", "Pick up",
                          "Customs Broker", "Gate out"):
            assert forbidden not in descs, f"FOB must not carry {forbidden!r}"


# ── EXW concept list ──────────────────────────────────────────────────────────

class TestExwConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "EXW")

    def test_descriptions_in_order(self, concepts):
        descs = [c.description for c in concepts]
        assert descs[0] == "Flete Internacional (COLLECT)"
        assert "Customs Broker" in descs
        assert "Operative Charge" in descs
        assert "Seal" in descs
        assert "Coordinación y Supervisión del Embarque" in descs
        assert "Agency Fee" in descs
        assert "Gate out" in descs
        assert "Terminal Fee" in descs
        assert "Pick up" in descs

    def test_collect_item_is_intl_and_zero(self, concepts):
        collect = concepts[0]
        assert collect.is_collect is True
        assert collect.amount_usd == 0.0
        assert collect.is_international is True
        assert collect.igv_applicable is False

    def test_terminal_fee_is_resolved_not_fixed(self, concepts):
        # Session L: Terminal Fee amount comes from port_costs at runtime.
        tf = next(c for c in concepts if c.description == "Terminal Fee")
        assert tf.unit == RESOLVED
        assert tf.amount_by_size is None
        assert tf.igv_applicable is True
        assert tf.is_international is False

    def test_gate_out_kept_fixed_no_clean_doc_source(self, concepts):
        # STOP-listed: export gate is per-depot/multi-valued — left at sheet value.
        gate = next(c for c in concepts if c.description == "Gate out")
        assert gate.unit == PER_CNTR
        assert gate.amount_usd == 150.0

    def test_per_cntr_extra_present(self, concepts):
        extra = [c for c in concepts if c.unit == PER_CNTR_EXTRA]
        assert len(extra) == 1
        assert extra[0].amount_usd == 25.0

    def test_dynamic_pickup_present(self, concepts):
        dyn = [c for c in concepts if c.unit == DYNAMIC]
        assert len(dyn) == 1
        assert dyn[0].description == "Pick up"


# ── FOB concept list — Ocean Freight only (Abel F3/F4 2026-07-06) ─────────────
# The FCL FOB EXPO TARIFA NETA (client-facing right-hand block) lists ONE
# client concept: Ocean Freight (COLLECT, by container size, 0.00). Handling
# 85 / Doc Fee 25 belong to a SEPARATE lower table headed "Los siguientes
# costos deben ser cobrados al exportador" (origin costs billed to the
# exporter) — not the net tariff. Session J (e20d521) read that lower table by
# mistake; F3/F4 corrects FOB to Ocean Freight only.

class TestFobConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "FOB")

    def test_exactly_one_concept(self, concepts):
        assert len(concepts) == 1

    def test_flete_collect_only(self, concepts):
        flete = concepts[0]
        assert flete.description == "Flete Internacional (COLLECT)"
        assert flete.amount_usd == 0.0
        assert flete.unit == PER_CNTR
        assert flete.is_collect is True
        assert flete.is_international is True
        assert flete.igv_applicable is False

    def test_no_handling_or_doc_fee(self, concepts):
        descs = {c.description for c in concepts}
        assert "Handling" not in descs
        assert "Doc Fee / Por BL" not in descs

    def test_no_resolved_items(self, concepts):
        assert not any(c.unit == RESOLVED for c in concepts)


# ── DAP concept list ──────────────────────────────────────────────────────────

class TestDapConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DAP")

    def test_descriptions_in_order(self, concepts):
        descs = [c.description for c in concepts]
        assert descs[0] == "THC"
        assert descs[1] == "ISPS"
        assert "BL Master" in descs
        assert "Coordinación y Supervisión del Embarque" in descs
        assert "Agency Fee" in descs
        assert "Gate in" in descs
        assert "Terminal Fee" in descs
        assert "Delivery" in descs

    def test_thc_isps_resolved_intl_no_igv(self, concepts):
        thc = next(c for c in concepts if c.description == "THC")
        isps = next(c for c in concepts if c.description == "ISPS")
        assert thc.unit == RESOLVED
        assert thc.is_international is True
        assert thc.igv_applicable is False
        assert isps.unit == RESOLVED
        assert isps.is_international is True
        assert isps.igv_applicable is False

    def test_bl_master_resolved_local_igv(self, concepts):
        bl = next(c for c in concepts if c.description == "BL Master")
        assert bl.unit == RESOLVED
        assert bl.is_international is False
        assert bl.igv_applicable is True

    def test_terminal_fee_resolved(self, concepts):
        tf = next(c for c in concepts if c.description == "Terminal Fee")
        assert tf.unit == RESOLVED
        assert tf.igv_applicable is True

    def test_gate_in_kept_fixed_no_clean_doc_source(self, concepts):
        # STOP-listed: no import-gate doc source — left at sheet value.
        gate = next(c for c in concepts if c.description == "Gate in")
        assert gate.unit == PER_CNTR
        assert gate.amount_usd == 205.0

    def test_coordinacion_agency_kept_fixed(self, concepts):
        coord = next(c for c in concepts if "Coordinación" in c.description)
        agency = next(c for c in concepts if c.description == "Agency Fee")
        assert coord.unit == PER_CNTR and coord.amount_usd == 190.0
        assert agency.unit == PER_BL and agency.amount_usd == 4.75

    def test_dynamic_delivery_present(self, concepts):
        dyn = [c for c in concepts if c.unit == DYNAMIC]
        assert len(dyn) == 1
        assert dyn[0].description == "Delivery"


# ── DDP concept list (Session L §2/§3/§4) ─────────────────────────────────────

class TestDdpConceptList:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DDP")

    def test_concept_descriptions(self, concepts):
        descs = [c.description for c in concepts]
        assert "THC" in descs
        assert "ISPS" in descs
        assert "Emisión MBL" in descs
        assert "Visto Bueno (Importación)" in descs
        assert "Terminal Fee" in descs
        assert "Operative Charge" in descs
        assert "Customs Broker" in descs
        assert "Delivery" in descs

    def test_gate_in_is_not_a_venta_concept(self, concepts):
        # Gate in is COST-only — must never appear in the client-facing concepts.
        assert not any("Gate in" in c.description for c in concepts)

    def test_thc_isps_intl_exempt(self, concepts):
        for d in ("THC", "ISPS"):
            c = next(x for x in concepts if x.description == d)
            assert c.is_international is True
            assert c.igv_applicable is False
            assert c.unit == RESOLVED

    def test_mbl_afecto_igv(self, concepts):
        mbl = next(c for c in concepts if c.description == "Emisión MBL")
        assert mbl.is_international is False
        assert mbl.igv_applicable is True
        assert mbl.unit == RESOLVED

    def test_vb_importacion_afecto_igv(self, concepts):
        vb = next(c for c in concepts if c.description == "Visto Bueno (Importación)")
        assert vb.is_international is False
        assert vb.igv_applicable is True
        assert vb.unit == RESOLVED

    def test_operative_charge_fixed_20_local(self, concepts):
        op = next(c for c in concepts if c.description == "Operative Charge")
        assert op.unit == PER_BL
        assert op.amount_usd == 20.0
        assert op.igv_applicable is True

    def test_customs_broker_resolved_local(self, concepts):
        cb = next(c for c in concepts if c.description == "Customs Broker")
        assert cb.unit == RESOLVED
        assert cb.is_international is False
        assert cb.igv_applicable is True


# ── build_agente_venta_items — EXW ───────────────────────────────────────────

class TestBuildExwItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "EXW")

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0, resolved_amounts=None):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd,
            resolved_amounts=resolved_amounts,
        )

    def test_collect_item_total_is_zero(self, concepts):
        items = self._items(concepts)
        collect = next(i for i in items if "COLLECT" in i["description"])
        assert collect["total"] == 0.0
        assert collect["is_international"] is True
        assert collect["igv_applicable"] is False

    def test_customs_broker_per_bl_flat(self, concepts):
        items = self._items(concepts, num_containers=3)
        cb = next(i for i in items if i["description"] == "Customs Broker")
        assert cb["total"] == 50.0  # flat per BL, not × 3

    def test_terminal_fee_resolved_from_port_doc(self, concepts):
        # Amount injected from port_costs (export) — here a synthetic doc value.
        items = self._items(concepts, resolved_amounts={"Terminal Fee": 331.45})
        tf = next(i for i in items if i["description"] == "Terminal Fee")
        assert tf["total"] == 331.45
        assert tf["is_local"] is True
        assert tf["igv_applicable"] is True

    def test_terminal_fee_omitted_when_unresolved(self, concepts):
        items = self._items(concepts, resolved_amounts=None)
        tf = [i for i in items if i["description"] == "Terminal Fee"]
        assert tf == []

    def test_gate_out_still_charged_fixed(self, concepts):
        items = self._items(concepts)
        gate = next(i for i in items if i["description"] == "Gate out")
        assert gate["total"] == 150.0

    def test_dynamic_pickup_omitted_when_zero(self, concepts):
        items = self._items(concepts, open_transport_usd=0.0)
        pickup = [i for i in items if i["description"] == "Pick up"]
        assert pickup == []

    def test_dynamic_pickup_included_when_nonzero(self, concepts):
        items = self._items(concepts, open_transport_usd=250.0)
        pickup = next(i for i in items if i["description"] == "Pick up")
        assert pickup["total"] == 250.0
        assert pickup["is_local"] is True

    def test_no_lcl_or_company_name_in_labels(self, concepts):
        items = self._items(concepts, open_transport_usd=100.0,
                            resolved_amounts={"Terminal Fee": 300.0})
        for item in items:
            assert "LCL" not in item["description"].upper()
            assert "Open Transport" not in item["description"]


# ── build_agente_venta_items — FOB (Ocean Freight only) ──────────────────────

class TestBuildFobItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("EXPO", "FOB")

    # Abel F3/F4 2026-07-06: FOB emits ONLY the collect ocean-freight line.
    def test_exactly_one_item(self, concepts):
        items = build_agente_venta_items(concepts, 1, "20STD")
        assert len(items) == 1

    def test_flete_collect_emitted_at_zero(self, concepts):
        items = build_agente_venta_items(concepts, 1, "20STD")
        flete = items[0]
        assert flete["description"] == "Flete Internacional (COLLECT)"
        assert flete["total"] == 0.0
        assert flete["is_international"] is True
        assert flete["igv_applicable"] is False

    def test_no_handling_or_doc_fee_items(self, concepts):
        # Handling / Doc Fee were the only local items — removed under F3/F4.
        items = build_agente_venta_items(concepts, 2, "20STD")
        descs = {i["description"] for i in items}
        assert "Handling" not in descs
        assert "Doc Fee / Por BL" not in descs

    def test_no_local_items_remain(self, concepts):
        items = build_agente_venta_items(concepts, 1, "20STD")
        assert not any(i.get("is_local") for i in items)


# ── build_agente_venta_items — DAP ───────────────────────────────────────────

class TestBuildDapItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DAP")

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0, resolved_amounts=None):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd,
            resolved_amounts=resolved_amounts,
        )

    def test_thc_resolved_intl_exempt(self, concepts):
        items = self._items(concepts, resolved_amounts={"THC": 65.0})
        thc = next(i for i in items if i["description"] == "THC")
        assert thc["is_international"] is True
        assert thc["igv_applicable"] is False
        assert thc["total"] == 65.0

    def test_isps_resolved_intl_exempt(self, concepts):
        items = self._items(concepts, resolved_amounts={"ISPS": 39.0})
        isps = next(i for i in items if i["description"] == "ISPS")
        assert isps["is_international"] is True
        assert isps["igv_applicable"] is False
        assert isps["total"] == 39.0

    def test_bl_master_resolved_local_igv(self, concepts):
        items = self._items(concepts, resolved_amounts={"BL Master": 55.0})
        bl = next(i for i in items if i["description"] == "BL Master")
        assert bl["is_local"] is True
        assert bl["igv_applicable"] is True
        assert bl["total"] == 55.0

    def test_resolved_items_omitted_when_not_supplied(self, concepts):
        items = self._items(concepts, resolved_amounts=None)
        descs = [i["description"] for i in items]
        assert "THC" not in descs
        assert "ISPS" not in descs
        assert "BL Master" not in descs
        assert "Terminal Fee" not in descs
        # but the fixed GT fees still render
        assert "Coordinación y Supervisión del Embarque" in descs
        assert "Gate in" in descs

    def test_gate_in_charged_fixed(self, concepts):
        items = self._items(concepts)
        gate = next(i for i in items if i["description"] == "Gate in")
        assert gate["total"] == 205.0

    def test_no_lcl_items(self, concepts):
        items = self._items(concepts, open_transport_usd=200.0,
                            resolved_amounts={"THC": 65.0, "Terminal Fee": 330.0})
        for item in items:
            assert "LCL" not in item["description"].upper()


# ── build_agente_venta_items — DDP ───────────────────────────────────────────

class TestBuildDdpItems:
    @pytest.fixture
    def concepts(self):
        return get_incoterm_concepts("IMPO", "DDP")

    def _resolved(self):
        return {
            "THC": 65.0,
            "ISPS": 39.0,
            "Emisión MBL": 55.0,
            "Visto Bueno (Importación)": 225.0,
            "Terminal Fee": 330.0,
            "Customs Broker": 110.0,
        }

    def _items(self, concepts, num_containers=1, container_type="20STD",
               open_transport_usd=0.0, resolved_amounts=None):
        return build_agente_venta_items(
            concepts, num_containers, container_type, open_transport_usd,
            resolved_amounts=resolved_amounts if resolved_amounts is not None else self._resolved(),
        )

    def test_thc_isps_exempt_in_ddp(self, concepts):
        items = self._items(concepts)
        for d in ("THC", "ISPS"):
            it = next(i for i in items if i["description"] == d)
            assert it["igv_applicable"] is False
            assert it["is_international"] is True

    def test_mbl_afecto_igv_in_ddp(self, concepts):
        items = self._items(concepts)
        mbl = next(i for i in items if i["description"] == "Emisión MBL")
        assert mbl["igv_applicable"] is True
        assert mbl["is_local"] is True
        assert mbl["total"] == 55.0

    def test_vb_importacion_afecto_igv_in_ddp(self, concepts):
        items = self._items(concepts)
        vb = next(i for i in items if i["description"] == "Visto Bueno (Importación)")
        assert vb["igv_applicable"] is True
        assert vb["is_local"] is True
        assert vb["total"] == 225.0

    def test_operative_charge_in_venta(self, concepts):
        items = self._items(concepts)
        op = next(i for i in items if i["description"] == "Operative Charge")
        assert op["total"] == 20.0
        assert op["igv_applicable"] is True

    def test_customs_broker_line_present(self, concepts):
        items = self._items(concepts)
        cb = next(i for i in items if i["description"] == "Customs Broker")
        assert cb["total"] == 110.0
        assert cb["igv_applicable"] is True

    def test_gate_in_never_in_venta(self, concepts):
        items = self._items(concepts)
        assert not any("Gate in" in i["description"] for i in items)

    def test_delivery_dynamic_included_when_nonzero(self, concepts):
        items = self._items(concepts, open_transport_usd=300.0)
        delivery = next(i for i in items if i["description"] == "Delivery")
        assert delivery["total"] == 300.0
        assert delivery["igv_applicable"] is True

    def test_ddp_total(self, concepts):
        items = self._items(concepts, open_transport_usd=0.0)
        total = sum(i["total"] for i in items)
        # THC 65 + ISPS 39 + MBL 55 + VB 225 + Terminal 330 + Operative 20 + Broker 110
        assert round(total, 2) == round(65 + 39 + 55 + 225 + 330 + 20 + 110, 2)

    def test_resolved_omitted_when_missing(self, concepts):
        # If a naviera figure is unavailable, the line is omitted (no default).
        items = self._items(concepts, resolved_amounts={"Customs Broker": 110.0})
        descs = [i["description"] for i in items]
        assert "THC" not in descs
        assert "Customs Broker" in descs   # broker still resolved
        assert "Operative Charge" in descs  # fixed fee still present


# ── Cliente local regression guard ───────────────────────────────────────────

class TestClienteLocalFallthrough:
    def test_none_for_cif(self):
        assert get_incoterm_concepts("EXPO", "CIF") is None

    def test_none_for_fca(self):
        assert get_incoterm_concepts("EXPO", "FCA") is None

    def test_none_for_ddu(self):
        assert get_incoterm_concepts("IMPO", "DDU") is None

    def test_none_for_empty_string(self):
        assert get_incoterm_concepts("EXPO", "") is None


# ── F1–F6 cross-incoterm assertions ──────────────────────────────────────────

class TestF1ToF6OnAgentePath:
    """
    Verify the 6 Session-I rendering fixes still hold on every registered
    incoterm when routed through the agente_internacional concept builder.
    Session L: amount source changed only — these structure/flag behaviors
    are preserved.
    """

    _RESOLVED = {
        "THC": 65.0, "ISPS": 39.0, "BL Master": 55.0, "Emisión MBL": 55.0,
        "Visto Bueno (Importación)": 225.0, "Terminal Fee": 330.0,
        "Customs Broker": 110.0,
    }

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f1_no_lcl_transport_items(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0,
            resolved_amounts=self._RESOLVED,
        )
        for item in items:
            assert "LCL" not in item["description"].upper()

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f2_no_duplicate_vb(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0,
            resolved_amounts=self._RESOLVED,
        )
        vb_items = [i for i in items if "visto bueno" in i["description"].lower()]
        assert len(vb_items) <= 1

    def test_f3_thc_isps_exempt_vb_mbl_afecto_in_ddp(self):
        # §4 reversal: in DDP, THC/ISPS exempt, MBL + VB afecto IGV.
        concepts = get_incoterm_concepts("IMPO", "DDP")
        items = build_agente_venta_items(concepts, 1, "20STD",
                                         resolved_amounts=self._RESOLVED)
        for item in items:
            if item["description"] in ("THC", "ISPS"):
                assert item["igv_applicable"] is False
            if item["description"] in ("Emisión MBL", "Visto Bueno (Importación)"):
                assert item["igv_applicable"] is True

    def test_f4_terminal_fee_single_item_no_split(self):
        for flujo, incoterm in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, incoterm)
            items = build_agente_venta_items(concepts, 1, "20STD",
                                             resolved_amounts=self._RESOLVED)
            tf_items = [i for i in items if i["description"] == "Terminal Fee"]
            assert len(tf_items) <= 1

    def test_f5_thc_isps_exempt_in_all_incoterms(self):
        for flujo, incoterm in registered_incoterms():
            concepts = get_incoterm_concepts(flujo, incoterm)
            items = build_agente_venta_items(concepts, 1, "20STD",
                                             resolved_amounts=self._RESOLVED)
            for item in items:
                if item["description"] in ("THC", "ISPS"):
                    assert item["igv_applicable"] is False

    @pytest.mark.parametrize("flujo,incoterm", registered_incoterms())
    def test_f6_no_transporter_company_name(self, flujo, incoterm):
        concepts = get_incoterm_concepts(flujo, incoterm)
        items = build_agente_venta_items(
            concepts, 1, "20STD", open_transport_usd=200.0,
            resolved_amounts=self._RESOLVED,
        )
        for item in items:
            assert "Open Transport" not in item["description"]


# ── Per-incoterm form-field visibility (registry-derived) ─────────────────────
# The New Quote form gates each agente_internacional FCL input on whether the
# concept it feeds is in the selected incoterm's registry set (Abel F3/F4
# 2026-07-06: "el incoterm determina la estructura de costos"). This helper is
# the single source of truth the template injects into the form JS, so the
# field set can never drift from _REGISTRY.
#
# Field → concept mapping:
#   naviera     → naviera-sourced RESOLVED charges (THC/ISPS/BL Master/
#                 Emisión MBL/Visto Bueno Importación)
#   terminal    → Terminal Fee
#   thc         → THC / ISPS
#   transporte  → the DYNAMIC Open-Transport concept (Pick up / Delivery)
#   oea         → Customs Broker
#   ddp_cif     → DDP CIF inputs (Valor Factura + Seguro) — DDP only
# (Flete Internacional, Tipo/N° Contenedor, Margen and the client-type selector
#  are structural to every FCL agente quote and stay ungated.)

_EXPECTED_FIELD_VISIBILITY = {
    ("EXPO", "FOB"): {"naviera": False, "terminal": False, "thc": False,
                      "transporte": False, "oea": False, "ddp_cif": False},
    ("EXPO", "EXW"): {"naviera": False, "terminal": True,  "thc": False,
                      "transporte": True,  "oea": True,  "ddp_cif": False},
    ("IMPO", "DAP"): {"naviera": True,  "terminal": True,  "thc": True,
                      "transporte": True,  "oea": False, "ddp_cif": False},
    ("IMPO", "DDP"): {"naviera": True,  "terminal": True,  "thc": True,
                      "transporte": True,  "oea": True,  "ddp_cif": True},
}


class TestAgenteFieldVisibility:
    @pytest.mark.parametrize("key,expected",
                             list(_EXPECTED_FIELD_VISIBILITY.items()))
    def test_matches_expected(self, key, expected):
        from core.fcl_agente_incoterm import agente_field_visibility
        flujo, inc = key
        assert agente_field_visibility(flujo, inc) == expected

    def test_unregistered_incoterm_returns_none(self):
        from core.fcl_agente_incoterm import agente_field_visibility
        # agente falls back to cliente_local for these → no field restriction.
        assert agente_field_visibility("EXPO", "CIF") is None
        assert agente_field_visibility("IMPO", "FOB") is None

    def test_fob_hides_all_optional_inputs(self):
        from core.fcl_agente_incoterm import agente_field_visibility
        vis = agente_field_visibility("EXPO", "FOB")
        assert not any(vis.values()), (
            "FOB is Ocean-Freight-only: every optional input must be hidden"
        )

    def test_case_insensitive(self):
        from core.fcl_agente_incoterm import agente_field_visibility
        assert (agente_field_visibility("expo", "exw")
                == agente_field_visibility("EXPO", "EXW"))


class TestAgenteFieldVisibilityMap:
    def test_map_has_all_registered_incoterms(self):
        from core.fcl_agente_incoterm import (agente_field_visibility_map,
                                              registered_incoterms)
        m = agente_field_visibility_map()
        for flujo, inc in registered_incoterms():
            assert f"{flujo}/{inc}" in m

    def test_map_values_match_helper(self):
        from core.fcl_agente_incoterm import (agente_field_visibility,
                                              agente_field_visibility_map,
                                              registered_incoterms)
        m = agente_field_visibility_map()
        for flujo, inc in registered_incoterms():
            assert m[f"{flujo}/{inc}"] == agente_field_visibility(flujo, inc)
